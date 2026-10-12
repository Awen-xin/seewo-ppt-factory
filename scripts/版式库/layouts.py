#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""希沃课件版式库 —— 几何模板引擎。

把已经验证过的几套构图沉淀成**参数化模板**：
    封面 / 竖条要点列 / 证据+追问 / 记录表 / 思维导图 /
    三卡片 / 双栏并列 / 步骤流程 / 结论条 / 配对活动

给每页一句 high-level 描述，模板负责算坐标、字号、行高与容器，
直接产出 seewo 技能（seewo-easinote-assistant-skill）可消费的 visualPlan。
这样"一句话出课件"不再靠 AI 每页现编坐标，稳定性来自模板而不是运气。

为什么能稳（三条都与技能校验器/渲染器的真实行为对齐）：

1. 渲染器**不缩字号，只会把过矮的框向下撑高**（page_renderer 里 fit=False，
   仅在 height_deficit>0 时 h += ceil(deficit)）。手工写坐标时"框偏矮"会
   静默长高、压到下面的元素。本库的**内容页**按客户端真实行高
   （components.REAL_LINE_HEIGHT_FACTOR = 1.42）反算框高，**声明即所需**，
   渲染端不再撑高，版面与设计稿完全一致（可用 check_geometry.py 复核）。

2. 工具页（table / mindmap）是**唯一例外**：硬约束是"元素框不得压到原生组件
   安全区（通用槽 y≥234，重叠 >2% 即报错）"，而不是"渲染端不撑高"。所以这两类页
   刻意按**校验口径**（系数 1.0）声明框，把头部整条收在 y=234 之上；渲染端撑高的
   那点高度落进组件自带的空白内边距里（第 6 课实测：脑图可视节点从 y≈360 才开始，
   表格从 y≈237 才开始），视觉上看不见。这是"合规优先"的取舍，不是疏漏。

3. 内容装不下时**不静默缩字**，而是在生成阶段直接抛错并指出要精简的文案 ——
   把问题暴露在"生成"这一步，而不是变成投影上的一处重叠或一次自动缩号。
"""

import math
import os
import sys

# ── 依赖 seewo 技能的度量与文本模块（只读，不修改技能本体）──────────
# 官方 skill 目录走统一配置中心（自动探测；可用环境变量 SEEWO_SKILL_DIR 覆盖）
_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
for _p in (_HERE, _PARENT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import seewo_config                                           # noqa: E402

SKILL_DIR = seewo_config.get_skill_dir() or ""
seewo_config.ensure_official_paths("design", "courseware")

try:
    import components as C                                    # noqa: E402
except ImportError:                                           # pragma: no cover
    raise SystemExit(
        "找不到 seewo 技能的度量模块。请设置环境变量 SEEWO_SKILL_DIR 指向\n"
        "  ...\\seewo-easinote-assistant-skill__skillhub\n"
        "当前值：%s" % SKILL_DIR)


# ── 字体方案（模块级，由 make_deck 按简报设置）───────────────────────
# 默认不动任何东西；换成 typography.PRESETS 里的预设即可整册换字换字号。
# 见 typography.py 的说明：scale 同时作用在 size 与 min 上，
# 否则 flow() 装不下时会自动降回原下限，放大等于白做。
TYPO = {"scale": 1.0, "fonts": {}, "fonts_bold": {}}


def set_typography(typo):
    """由生成器调用；返回旧值便于还原。"""
    global TYPO
    old, TYPO = TYPO, dict(typo or {})
    return old


def _scale():
    return float(TYPO.get("scale", 1.0))


class LayoutError(Exception):
    """文案在当前模板里装不下 —— 必须精简内容或换模板。"""


# ── 画布与版面常量（与技能校验器一致）──────────────────────────────
W, H = 1280, 720            # 画布
M = 72                      # 左右页边距
CW = W - 2 * M              # 内容宽 1136
BAR_W = 8                   # 左侧锚点竖条宽
TOP = 54                    # 内容页首个文本块的 y
BOTTOM = 672                # 内容页可用底边
TOOL_SLOT_Y = 234           # 希沃原生组件安全区顶边（通用槽）

LINE_FACTOR = C.REAL_LINE_HEIGHT_FACTOR   # 1.42 客户端真实行高系数
VALIDATE_FACTOR = 1.0                     # 校验器口径（工具页用）


# ── 度量 ───────────────────────────────────────────────────────────
def _runs(text):
    """把 '第一行\\n第二行' 变成 measure_text_layout 要的 lines_of_runs。"""
    return [[{"text": line, "bold": False, "color": None}]
            for line in str(text).split("\n")]


def _measure(text, w, max_h, size, ls, padding=0, factor=LINE_FACTOR):
    return C.measure_text_layout(
        _runs(text), w, max_h, size, ls,
        margin=(padding,) * 4, line_height_factor=factor)


def _height_of(text, w, size, ls, padding=0, factor=LINE_FACTOR):
    """文本所需高度（含上下 padding）。"""
    inner = _measure(text, w, 10 ** 6, size, ls, padding, factor)["required_height"]
    return int(math.ceil(inner + 2 * padding))


def _short(text, limit=22):
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def autosize(text, x, y, w, max_h, size, min_size, ls=1.4, padding=0,
             factor=LINE_FACTOR):
    """在给定框高内选最大可用字号，返回 (box, size)；到下限仍装不下则报错。"""
    k = _scale()
    size, min_size = int(round(size * k)), int(round(min_size * k))
    for candidate in range(int(size), int(min_size) - 1, -1):
        if _measure(text, w, max_h, candidate, ls, padding, factor)["fits"]:
            height = max(_height_of(text, w, candidate, ls, padding, factor),
                         candidate * 1.22)
            return {"x": int(x), "y": int(y), "w": int(w),
                    "h": int(math.ceil(height))}, candidate
    raise LayoutError(
        "%dpx 已是下限仍装不下：框宽 %dpx / 可用高 %dpx —— 请精简文案：%s"
        % (min_size, w, max_h, _short(text)))


def flow(blocks, top, bottom, gap=None, factor=LINE_FACTOR):
    """纵向流式排版。

    blocks: [{key, text, x, w, size, min, ls, padding?, gap?}]
      * gap 默认值 = 参数 gap；每个块可用自己的 gap 覆盖（表示"本块之前的间距"）
    返回: [{"key", "box", "size"}]，自上而下顺序排布。

    超出可用高度时**优先降字号**（从当前最大的可降块开始，逐级 1px），
    降到各自下限仍装不下才报错 —— 所以"能排"和"该精简"有明确分界。
    """
    if not blocks:
        return []
    default_gap = 10 if gap is None else gap
    k = _scale()                       # 字号倍率；下限同比放大，否则装不下时会降回原尺寸
    sizes = [int(round(int(b["size"]) * k)) for b in blocks]
    mins = [int(round(int(b["min"]) * k)) for b in blocks]
    avail = bottom - top

    def total(chosen):
        height = sum(_height_of(b["text"], b["w"], s, b["ls"],
                                b.get("padding", 0), factor)
                     for b, s in zip(blocks, chosen))
        return height + sum(b.get("gap", default_gap) for b in blocks[1:])

    while total(sizes) > avail:
        pick = max((i for i in range(len(blocks)) if sizes[i] > mins[i]),
                   key=lambda i: sizes[i], default=None)
        if pick is None:
            raise LayoutError(
                "本页内容超出可用高度 %dpx（下限字号也排不下）—— 请精简文案：%s"
                % (avail, " | ".join(_short(b["text"]) for b in blocks)))
        sizes[pick] -= 1

    laid, y = [], top
    for index, (block, size) in enumerate(zip(blocks, sizes)):
        if index:
            y += block.get("gap", default_gap)
        height = max(_height_of(block["text"], block["w"], size, block["ls"],
                                block.get("padding", 0), factor),
                     size * 1.22)
        height = int(math.ceil(height))
        laid.append({"key": block["key"], "size": size,
                     "box": {"x": int(block["x"]), "y": int(y),
                             "w": int(block["w"]), "h": height}})
        y += height
    return laid


# ── 元素构造 ───────────────────────────────────────────────────────
def _t(source, role, box, size, color, bold=False, ls=1.4, **extra):
    """构造文本元素。

    字体由 TYPO 按 role 决定：
      * 没配字体 → 不写 font 键，渲染器用默认（微软雅黑），bold 照旧
      * 配了字体 → 写 font 键；bold 时换用 fonts_bold 里的粗一档字重，
        并把 bold 标记吃掉（避免客户端伪粗把笔画糊在一起）
    """
    style = {"fontSize": int(size), "color": color, "lineSpacing": float(ls)}
    fonts = TYPO.get("fonts") or {}
    bold_fonts = TYPO.get("fonts_bold") or {}
    face = (bold_fonts.get(role) if bold else None) or fonts.get(role)
    if face:
        style["font"] = face
        bold = False            # 字重已经由字体本身表达，不再叠 bold
    if bold:
        style["bold"] = True
    style.update(extra)
    return {"kind": "text", "source": source, "role": role, "box": box,
            "style": style}


def _s(shape, box, fill):
    return {"kind": "shape", "shape": shape, "box": box, "style": {"fill": fill}}


def _dot(x, y, d, fill):
    return _s("oval", {"x": int(x), "y": int(y), "w": int(d), "h": int(d)}, fill)


# ── 配图 ───────────────────────────────────────────────────────────
# 契约（取自技能 visual_validator.py）：
#   role ∈ illustration / photo / diagram / data
#   fit  只有 "cover" 合法，且会把图当背景 → 版式库一律不写 fit
#   caption 10~80 字，渲染器在配图底部画半透明图注条，图注计入页面内容密度
#   area ≤ 0.8 * W * H（配图不得当背景）；带图注时 w ≥ 200、h ≥ 60
IMG_ROLES = ("illustration", "photo", "diagram", "data")
CAPTION_MIN, CAPTION_MAX = 10, 80
MIN_IMG_W, MIN_IMG_H = 200, 60
MAX_IMG_AREA = 0.8 * W * H


def _img(src, role, box, caption=None):
    """构造一个 image 前景元素；坐标不合法时直接抛错（暴露在生成阶段）。"""
    role = str(role or "photo").strip()
    if role not in IMG_ROLES:
        raise LayoutError("配图 role=%r 不合法；可用：%s"
                          % (role, "、".join(IMG_ROLES)))
    d = {k: int(box[k]) for k in ("x", "y", "w", "h")}
    if d["w"] * d["h"] > MAX_IMG_AREA:
        raise LayoutError("配图 %s 面积过大（>画布 80%%），会被当成背景" % src)
    cap = (caption or "").strip()
    if cap:
        if not (CAPTION_MIN <= len(cap) <= CAPTION_MAX):
            raise LayoutError("配图 %s 图注 %d 字，须在 %d~%d 字之间"
                              % (os.path.basename(src), len(cap),
                                 CAPTION_MIN, CAPTION_MAX))
        if d["w"] < MIN_IMG_W or d["h"] < MIN_IMG_H:
            raise LayoutError("带图注的配图 %s 需 ≥%dx%d，当前 %dx%d"
                              % (os.path.basename(src), MIN_IMG_W, MIN_IMG_H,
                                 d["w"], d["h"]))
    e = {"kind": "image", "source": str(src), "role": role, "box": d}
    if cap:
        e["caption"] = cap
    return e


def _images(page):
    """把简报里的 images 字段规范化成 image 元素列表。

    支持两种写法：
        "images": [{"src": "...", "role": "photo", "box": {...}, "caption": "..."}]
        "images": [["...jpg", 72, 380, 360, 220, "可选图注"]]
    """
    out = []
    for raw in (page.get("images") or []):
        if isinstance(raw, dict):
            out.append(_img(raw.get("src") or raw.get("source"),
                            raw.get("role"), raw.get("box"), raw.get("caption")))
        elif isinstance(raw, (list, tuple)):
            src, x, y, w, h = raw[:5]
            cap = raw[5] if len(raw) > 5 else None
            out.append(_img(src, raw[6] if len(raw) > 6 else "photo",
                            {"x": x, "y": y, "w": w, "h": h}, cap))
        else:
            raise LayoutError("images 条目格式不认识：%r" % (raw,))
    return out


def _bar(y=TOP, height=48, theme=None):
    return _s("rect", {"x": M, "y": int(y + 6), "w": BAR_W, "h": int(height)},
              (theme or {})["gold"])


def _plan(intent, rationale, background, elements):
    return {"teachingIntent": intent, "designRationale": rationale,
            "background": background, "elements": elements}


def _item_text(item):
    if isinstance(item, dict):
        title = str(item.get("title") or item.get("heading") or "").strip()
        body = str(item.get("text") or item.get("body") or "").strip()
        return title + ("\n" if title and body else "") + body
    return str(item)


def _plain(p, key):
    value = p.get(key)
    return str(value).strip() if value else ""


# ── 模板注册 ───────────────────────────────────────────────────────
TEMPLATES = {}


def template(name, slots, intent="moment", rationale="", label=""):
    def register(fn):
        fn.template_name = name
        fn.slots = tuple(slots)
        fn.intent = intent
        fn.default_rationale = rationale
        fn.label = label or name
        TEMPLATES[name] = fn
        return fn
    return register


# ══════════════════════════════════════════════════════════════════
# 1. 封面
# ══════════════════════════════════════════════════════════════════
@template("cover", ("title", "lead", "body"), intent="moment", label="封面",
          rationale="课题首屏：深绿整版底承载主题重量，左侧金色竖条与主标题顶对齐形成视觉锚点，"
                    "下半部按『学段信息 → 分隔线 → 副题』三段纵向排布，营造正式感。")
def tpl_cover(p, t, note):
    # 有配图时主标题收窄到左半，右侧留给整幅情境大图
    imgs = _images(p)
    has_img = len(imgs) > 0
    if has_img and len(imgs) != 1:
        raise LayoutError("cover 最多挂 1 张配图，当前 %d 张" % len(imgs))
    x0, tw = 116, (620 if has_img else 1000)
    title_box, title_size = autosize(p["title"], x0, 200, tw, 132, 64, 42, 1.15)

    y = title_box["y"] + title_box["h"] + 26
    lead_box = lead_size = None
    if _plain(p, "lead"):
        lead_box, lead_size = autosize(p["lead"], x0 + 4, y, tw - 20, 66, 24, 22, 1.3)
        y = lead_box["y"] + lead_box["h"] + 30

    line_y = int(y)
    body_box = body_size = None
    if _plain(p, "body"):
        body_box, body_size = autosize(p["body"], x0 + 4, line_y + 26, tw - 20, 80,
                                       26, 22, 1.3)

    elements = [_s("rect", {"x": 80, "y": 198, "w": 8,
                            "h": max(80, line_y - 8 - 198)}, t["gold"]),
                _t("title", "title", title_box, title_size, t["white"], True, 1.15)]
    if lead_box:
        elements.append(_t("lead", "lead", lead_box, lead_size, t["meta"], ls=1.3))
    elements.append(_s("rect", {"x": 120, "y": line_y, "w": 320, "h": 2}, t["gold"]))
    if body_box:
        elements.append(_t("body", "body", body_box, body_size, t["sub"], ls=1.3))

    if has_img:
        # 封面图固定占画布右侧：x 780~1208，纵向与标题区对齐并适度下探
        ib = imgs[0]["box"]
        ib.update({"x": 780, "y": 132, "w": 428, "h": 456})
        elements.append(imgs[0])

    return {"layout": "authored_canvas", "role": "cover",
            "visualPlan": _plan("moment", note, {"type": "solid", "color": t["deep"]},
                                elements)}


# ══════════════════════════════════════════════════════════════════
# 2. 竖条要点列（导入 / 单栏要点）
# ══════════════════════════════════════════════════════════════════
@template("bullets", ("title", "lead", "body", "items"), intent="moment",
          label="竖条要点列",
          rationale="米白底上先立课题节奏：左侧金色竖条延续封面结构语言，引导语与解释上下分层，"
                    "底部要点用同色圆点并列，最后一条用金色圆点与深绿加粗收束。")
def tpl_bullets(p, t, note):
    imgs = _images(p)
    if imgs and len(imgs) != 2:
        raise LayoutError("bullets 挂配图时需 2 张（左右各一，排在要点下方），"
                          "当前 %d 张" % len(imgs))
    has_img = bool(imgs)

    blocks = [dict(key="title", text=p["title"], x=104, w=1100,
                   size=48, min=42, ls=1.15, gap=0)]
    if _plain(p, "lead"):
        blocks.append(dict(key="lead", text=p["lead"], x=72, w=1140,
                           size=30, min=23, ls=1.4, gap=22))
    if _plain(p, "body"):
        blocks.append(dict(key="body", text=p["body"], x=72, w=1140,
                           size=26, min=22, ls=1.5, gap=18))
    items = [_item_text(i) for i in (p.get("items") or [])]
    for index, text in enumerate(items):
        blocks.append(dict(key="item.%d" % index, text=text, x=112, w=1090,
                           size=26, min=22, ls=1.3, gap=14 if index == 0 else 16))
    # 有配图时在要点下方留出 172px 高的图带（两栏并列），正文区相应压缩
    laid = flow(blocks, TOP, 476 if has_img else BOTTOM)

    elements = [_bar(TOP, 48, t)]
    for block, item in zip(blocks, laid):
        key, box, size = block["key"], item["box"], item["size"]
        if key.startswith("item."):
            last = key == "item.%d" % (len(items) - 1)
            elements.append(_dot(76, box["y"] + int((size * LINE_FACTOR - 16) / 2), 16,
                                 t["gold"] if last else t["accent"]))
            elements.append(_t(key, "item", box, size,
                               t["deep"] if last else t["ink"], bold=last, ls=1.3))
        elif key == "title":
            elements.append(_t("title", "title", box, size, t["deep"], True, 1.15))
        elif key == "lead":
            elements.append(_t("lead", "lead", box, size, t["mid"], ls=1.4))
        else:
            elements.append(_t("body", "body", box, size, t["ink"], ls=1.5))

    if has_img:
        # 要点下方横排两图（各占半宽），图注压在图上
        for index, im in enumerate(imgs):
            ib = im["box"]
            ib.update({"x": 72 + index * 580, "y": 490, "w": 556, "h": 174})
            elements.append(im)

    return {"layout": "authored_canvas",
            "visualPlan": _plan("moment", note, {"type": "solid", "color": t["paper"]},
                                elements)}


# ══════════════════════════════════════════════════════════════════
# 3. 证据 + 追问（探究页）
# ══════════════════════════════════════════════════════════════════
@template("evidence", ("title", "lead", "body", "items", "question"), intent="evidence",
          label="证据 + 追问",
          rationale="探究页在一屏内完成『提出问题—给证据—列要点—收束追问』四层递进："
                    "要点用小圆点并列，底部浅绿圆角问题框制造认知聚焦，是页面唯一强调元素。")
def tpl_evidence(p, t, note):
    question = _plain(p, "question")
    imgs = _images(p)
    if imgs and len(imgs) != 1:
        raise LayoutError("evidence 最多挂 1 张配图，当前 %d 张" % len(imgs))
    has_img = bool(imgs)
    # 有图时文字区收窄到左侧，右侧留 420px 竖条放配图
    lead_w = 716 if has_img else 1140
    pad = 24
    q_size = 32
    q_card = 0
    if question:
        q_card = _height_of(question, 1140, q_size, 1.3, pad) + 16

    blocks = [dict(key="title", text=p["title"], x=104, w=1100,
                   size=44, min=42, ls=1.15, gap=0)]
    if _plain(p, "lead"):
        blocks.append(dict(key="lead", text=p["lead"], x=72, w=lead_w,
                           size=28, min=23, ls=1.4, gap=20))
    if _plain(p, "body"):
        blocks.append(dict(key="body", text=p["body"], x=72, w=lead_w,
                           size=25, min=22, ls=1.5, gap=16))
    items = [_item_text(i) for i in (p.get("items") or [])]
    for index, text in enumerate(items):
        blocks.append(dict(key="item.%d" % index, text=text, x=108,
                           w=lead_w - 40,
                           size=24, min=22, ls=1.3, gap=14 if index == 0 else 12))
    laid = flow(blocks, TOP, BOTTOM - (q_card + 26 if q_card else 0))

    elements = [_bar(TOP, 48, t)]
    for block, item in zip(blocks, laid):
        key, box, size = block["key"], item["box"], item["size"]
        if key.startswith("item."):
            elements.append(_dot(76, box["y"] + int((size * LINE_FACTOR - 14) / 2), 14,
                                 t["accent"]))
            elements.append(_t(key, "item", box, size, t["ink"], ls=1.3))
        elif key == "title":
            elements.append(_t("title", "title", box, size, t["deep"], True, 1.15))
        elif key == "lead":
            elements.append(_t("lead", "lead", box, size, t["mid"], ls=1.4))
        else:
            elements.append(_t("body", "body", box, size, t["ink"], ls=1.5))

    if q_card:
        card_y = BOTTOM - q_card
        elements.append(_s("rounded", {"x": 72, "y": card_y, "w": 1140, "h": q_card},
                           t["light"]))
        elements.append(_t("question", "question",
                           {"x": 114, "y": card_y + 10, "w": 1060,
                            "h": q_card - 20}, q_size, t["deep"], True, 1.3))

    if has_img:
        ib = imgs[0]["box"]
        ib.update({"x": 812, "y": 143, "w": 396, "h": 396})
        elements.append(imgs[0])

    return {"layout": "authored_canvas",
            "visualPlan": _plan("evidence", note, {"type": "solid", "color": t["paper"]},
                                elements)}


# ══════════════════════════════════════════════════════════════════
# 4 / 5. 原生工具页（记录表 / 思维导图）
#   头部必须收在安全槽 y=234 之上，故按校验口径(1.0)声明框高。
# ══════════════════════════════════════════════════════════════════
def _tool_header(p, t, title_size, lead_size, lead_w, gap_title, gap_lead,
                 top=TOP, bottom=TOOL_SLOT_Y):
    """原生工具页的头部文字：必须整条收在安全槽 y=234 之上。

    这类页刻意用**校验口径**（系数 1.0）声明框高 —— 因为硬约束是"声明框不得
    压到安全槽"，而不是"渲染端不撑高"。撑高的部分会落到组件自带的空白内边距里，
    视觉上看不见（第 6 课实测：脑图组件可视节点从 y≈360 才开始）。
    """
    blocks = [dict(key="title", text=p["title"], x=104, w=1100,
                   size=title_size, min=42, ls=1.15, gap=0)]
    if _plain(p, "lead"):
        blocks.append(dict(key="lead", text=p["lead"], x=72, w=lead_w,
                           size=lead_size, min=22, ls=1.4, gap=gap_title))
    items = [_item_text(i) for i in (p.get("items") or [])]
    for index, text in enumerate(items):
        blocks.append(dict(key="item.%d" % index, text=text, x=72, w=lead_w,
                           size=22, min=22, ls=1.25,
                           gap=gap_lead if index == 0 else 4))
    laid = flow(blocks, top, bottom, factor=VALIDATE_FACTOR)
    elements = [_bar(top, 48, t)]
    for block, item in zip(blocks, laid):
        key, box, size = block["key"], item["box"], item["size"]
        role = "item" if key.startswith("item.") else key
        color = t["deep"] if key == "title" else (t["mid"] if key == "lead" else t["ink"])
        elements.append(_t(key, role, box, size, color,
                           bold=(key == "title"), ls=block["ls"]))
    return elements


@template("record_table", ("title", "lead"), intent="evidence", label="记录表",
          rationale="记录页由希沃表格组件主导，文字只承担提问与填写提示，全部压在组件安全区上方，"
                    "保证表格完整可见、不被文字挤压。")
def tpl_record_table(p, t, note):
    elements = _tool_header(p, t, title_size=44, lead_size=26, lead_w=1140,
                            gap_title=22, gap_lead=10, top=TOP)
    table = _plain(p, "table") or p.get("table") or ""
    if not str(table).strip():
        raise LayoutError("record_table 页缺少 table（markdown 表格文本）")
    return {"layout": "tool_page",
            "subjectTool": {"type": "table", "teachingIntent": "structure-mapping",
                            "data": {"markdownTable": str(table).strip()}},
            "visualPlan": _plan("evidence", note, {"type": "solid", "color": t["paper"]},
                                elements)}


@template("mindmap", ("title", "lead", "items"), intent="summary", label="思维导图",
          rationale="结构页把零散例子收成一张分类图，文字全部排在脑图生长区上方："
                    "标题、任务引导、分层说明自上而下纵向排列，避免与节点争夺注意力。")
def tpl_mindmap(p, t, note):
    # 脑图页头部内容最多（标题+引导+2条结构说明），顶部上移到 y=30、间距压到
    # 12/6 才能整条收在安全槽 y=234 之上（第 6 课实测值）。
    elements = _tool_header(p, t, title_size=44, lead_size=24, lead_w=1140,
                            gap_title=12, gap_lead=6, top=30)
    markdown = _plain(p, "markdown") or p.get("markdown") or ""
    if not str(markdown).strip():
        raise LayoutError("mindmap 页缺少 markdown（脑图层级文本）")
    return {"layout": "tool_page",
            "subjectTool": {"type": "mindmap", "teachingIntent": "structure-mapping",
                            "data": {"markdown": str(markdown).strip()}},
            "visualPlan": _plan("summary", note, {"type": "solid", "color": t["paper"]},
                                elements)}


# ══════════════════════════════════════════════════════════════════
# 6. 三卡片（实践 / 方案对比）
# ══════════════════════════════════════════════════════════════════
@template("cards3", ("title", "lead", "body", "items", "summary"), intent="sequence",
          label="三卡片 + 结论条",
          rationale="实践页用三张同构卡片并列呈现三种做法，卡片承担『选取部位 + 种植方法』的结构分区，"
                    "底部深色结论条把核心结论从正文里拎出来，形成清晰的对比阅读节奏。")
def tpl_cards3(p, t, note):
    items = [_item_text(i) for i in (p.get("items") or [])][:3]
    if len(items) < 3:
        raise LayoutError("cards3 需要 3 条 items（当前 %d 条）" % len(items))
    # cards3 卡片只有 164px 高，塞进配图后文字只剩一行 —— 图文并列请改用 photo_trio
    if _images(p):
        raise LayoutError("cards3 卡片过矮，不能挂配图；需要图文三栏请改用 photo_trio")

    blocks = [dict(key="title", text=p["title"], x=104, w=1100,
                   size=44, min=42, ls=1.15, gap=0)]
    if _plain(p, "lead"):
        blocks.append(dict(key="lead", text=p["lead"], x=72, w=1140,
                           size=27, min=22, ls=1.4, gap=20))
    if _plain(p, "body"):
        blocks.append(dict(key="body", text=p["body"], x=72, w=1140,
                           size=23, min=22, ls=1.45, gap=16))
    laid = flow(blocks, TOP, 366)

    card_y, card_h, card_w, card_gap = 380, 164, 360, 28
    elements = [_bar(TOP, 48, t)]
    for block, item in zip(blocks, laid):
        key, box, size = block["key"], item["box"], item["size"]
        color = t["deep"] if key == "title" else (t["mid"] if key == "lead" else t["ink"])
        elements.append(_t(key, key, box, size, color,
                           bold=(key == "title"), ls=block["ls"]))

    for index, text in enumerate(items):
        card_x = M + index * (card_w + card_gap)
        elements.append(_s("rounded", {"x": card_x, "y": card_y, "w": card_w,
                                       "h": card_h}, t["light"]))
        inner_box, inner_size = autosize(text, card_x + 28, card_y + 24,
                                         card_w - 56, card_h - 48, 25, 22, 1.45)
        elements.append(_t("item.%d" % index, "item", inner_box, inner_size,
                           t["cardInk"], ls=1.45))

    if _plain(p, "summary"):
        pad = 24
        size = 30
        card_h_summary = _height_of(p["summary"], 1140, size, 1.3, pad)
        summary_y = 562
        elements.append(_t("summary", "summary",
                           {"x": 72, "y": summary_y, "w": 1140, "h": card_h_summary},
                           size, t["white"], True, 1.3,
                           fill=t["deep"], fillOpacity=100, rounded=True,
                           radius=0.06, padding=pad))

    return {"layout": "authored_canvas",
            "visualPlan": _plan("sequence", note, {"type": "solid", "color": t["paper"]},
                                elements)}


# ══════════════════════════════════════════════════════════════════
# 7. 双栏并列（对比 / 辨析）
# ══════════════════════════════════════════════════════════════════
@template("two_col", ("title", "lead", "items", "summary"), intent="compare",
          label="双栏并列",
          rationale="两组同构信息左右并列，两栏字段、行数、字号完全一致，浅绿圆角卡片承担分组；"
                    "底部深色结论条给出差异总结，形成对照阅读。")
def tpl_two_col(p, t, note):
    items = [_item_text(i) for i in (p.get("items") or [])]
    if len(items) != 2:
        raise LayoutError("two_col 需要正好 2 条 items（左右栏各一条），当前 %d 条" % len(items))
    imgs = _images(p)
    if imgs and len(imgs) != 2:
        raise LayoutError("two_col 挂配图时需正好 2 张（左右卡各一张），当前 %d 张" % len(imgs))

    blocks = [dict(key="title", text=p["title"], x=104, w=1100,
                   size=44, min=42, ls=1.15, gap=0)]
    if _plain(p, "lead"):
        blocks.append(dict(key="lead", text=p["lead"], x=72, w=1140,
                           size=26, min=22, ls=1.4, gap=20))
    laid = flow(blocks, TOP, 300)

    if imgs:
        # 图文双栏：卡片加高，左半幅配图、文字排在卡片右侧（横向图文卡）
        col_y, col_h, col_w, col_gap = 302, 268, 556, 24
        IMG_W = 186
    else:
        col_y, col_h, col_w, col_gap = 316, 244, 556, 24
        IMG_W = 0
    elements = [_bar(TOP, 48, t)]
    for block, item in zip(blocks, laid):
        key, box, size = block["key"], item["box"], item["size"]
        color = t["deep"] if key == "title" else t["mid"]
        elements.append(_t(key, key, box, size, color,
                           bold=(key == "title"), ls=block["ls"]))

    for index, text in enumerate(items):
        col_x = M + index * (col_w + col_gap)
        elements.append(_s("rounded", {"x": col_x, "y": col_y, "w": col_w,
                                       "h": col_h}, t["light"]))
        if imgs:
            ib = imgs[index]["box"]
            ib.update({"x": col_x + 14, "y": col_y + 24, "w": IMG_W,
                       "h": col_h - 48})
            elements.append(imgs[index])
            inner_box, inner_size = autosize(text, col_x + 14 + IMG_W + 20,
                                             col_y + 26, col_w - IMG_W - 68,
                                             col_h - 52, 24, 21, 1.42)
        else:
            inner_box, inner_size = autosize(text, col_x + 30, col_y + 28,
                                             col_w - 60, col_h - 56, 25, 22, 1.45)
        elements.append(_t("item.%d" % index, "item", inner_box, inner_size,
                           t["cardInk"], ls=1.42 if imgs else 1.45))

    if _plain(p, "summary"):
        pad = 22
        size = 28
        summary_h = _height_of(p["summary"], 1140, size, 1.3, pad)
        sy = 600 if imgs else 592
        if sy + summary_h > 672:
            raise LayoutError("two_col 摘要条超出底边（%d>672），请精简摘要"
                              % (sy + summary_h))
        elements.append(_t("summary", "summary",
                           {"x": 72, "y": sy, "w": 1140, "h": summary_h},
                           size, t["white"], True, 1.3,
                           fill=t["deep"], fillOpacity=100, rounded=True,
                           radius=0.06, padding=pad))

    return {"layout": "authored_canvas",
            "visualPlan": _plan("compare", note, {"type": "solid", "color": t["paper"]},
                                elements)}


# ══════════════════════════════════════════════════════════════════
# 7b. 双栏图文（观察记录：一行两图 + 说明）
# ══════════════════════════════════════════════════════════════════
@template("photo_pair", ("title", "lead", "items", "summary"), intent="compare",
          label="双栏图文",
          rationale="两张同尺寸实物图左右并列，图注直接压在图上，说明文字收在卡片下半；"
                    "底部深色结论条给出共性结论，形成『先看形态、再得结论』的观察节奏。")
def tpl_photo_pair(p, t, note):
    items = [_item_text(i) for i in (p.get("items") or [])]
    if len(items) != 2:
        raise LayoutError("photo_pair 需要正好 2 条 items，当前 %d 条" % len(items))
    imgs = _images(p)
    if len(imgs) != 2:
        raise LayoutError("photo_pair 需要正好 2 张配图，当前 %d 张" % len(imgs))

    blocks = [dict(key="title", text=p["title"], x=104, w=1100,
                   size=44, min=42, ls=1.15, gap=0)]
    if _plain(p, "lead"):
        blocks.append(dict(key="lead", text=p["lead"], x=72, w=1140,
                           size=25, min=22, ls=1.4, gap=18))
    laid = flow(blocks, TOP, 290)

    # variant="stack"：图上文下（图占满卡宽，适合展示形态细节）
    # 缺省         ：图左文右（图窄、文字宽，适合图文对照精读）
    # 两种变体元素轮廓不同 —— 相邻页用不同变体可避免被判"版面高度雷同"。
    stack = str(p.get("variant") or "").strip() == "stack"
    col_y, col_h, col_w, col_gap = 288, 292, 556, 24
    IMG_H = 132
    elements = [_bar(TOP, 48, t)]
    for block, item in zip(blocks, laid):
        key, box, size = block["key"], item["box"], item["size"]
        color = t["deep"] if key == "title" else t["mid"]
        elements.append(_t(key, key, box, size, color,
                           bold=(key == "title"), ls=block["ls"]))

    IMG_W = 210     # 带图注的配图，技能硬下限为 200px 宽
    for index, text in enumerate(items):
        col_x = M + index * (col_w + col_gap)
        elements.append(_s("rounded", {"x": col_x, "y": col_y, "w": col_w,
                                       "h": col_h}, t["light"]))
        ib = imgs[index]["box"]
        if stack:
            ib.update({"x": col_x + 12, "y": col_y + 12,
                       "w": col_w - 24, "h": IMG_H})
            tx, ty = col_x + 26, col_y + 12 + IMG_H + 14
            tw = col_w - 52
        else:
            ib.update({"x": col_x + 12, "y": col_y + 26,
                       "w": IMG_W, "h": col_h - 64})
            tx, ty = col_x + IMG_W + 26, col_y + 26
            tw = col_w - IMG_W - 64
        elements.append(imgs[index])
        inner_box, inner_size = autosize(text, tx, ty, tw,
                                         col_h - (ty - col_y) - 14, 24, 21, 1.42)
        elements.append(_t("item.%d" % index, "item", inner_box, inner_size,
                           t["cardInk"], ls=1.42))

    if _plain(p, "summary"):
        # 结论条紧贴卡片下沿，最多两行；不够高时明确报错而不是静默重叠
        pad, size = 16, 24
        sh = _height_of(p["summary"], 1140, size, 1.3, pad)
        sy = col_y + col_h + 12
        if sy + sh > 672:
            raise LayoutError("photo_pair 摘要条超出底边（%d>672），请精简摘要或"
                              "把结论并入其中一条 items" % (sy + sh))
        elements.append(_t("summary", "summary", {"x": 72, "y": sy, "w": 1140,
                                                 "h": sh},
                           size, t["white"], True, 1.3,
                           fill=t["deep"], fillOpacity=100, rounded=True,
                           radius=0.06, padding=pad))

    return {"layout": "authored_canvas",
            "visualPlan": _plan("compare", note, {"type": "solid", "color": t["paper"]},
                                elements)}


# ══════════════════════════════════════════════════════════════════
# 7c. 三联图鉴（观察记录：一排三图 + 逐条说明）
# ══════════════════════════════════════════════════════════════════
@template("photo_trio", ("title", "lead", "body", "items"), intent="evidence",
          label="三联图鉴",
          rationale="一排三张同尺寸实物图并列，图注压在图上，说明文字贴在对应图下，"
                    "形成『横看形态差异、纵读说明要点』的图鉴式观察版。")
def tpl_photo_trio(p, t, note):
    items = [_item_text(i) for i in (p.get("items") or [])]
    if len(items) != 3:
        raise LayoutError("photo_trio 需要正好 3 条 items，当前 %d 条" % len(items))
    imgs = _images(p)
    if len(imgs) != 3:
        raise LayoutError("photo_trio 需要正好 3 张配图，当前 %d 张" % len(imgs))

    blocks = [dict(key="title", text=p["title"], x=104, w=1100,
                   size=44, min=42, ls=1.15, gap=0)]
    if _plain(p, "lead"):
        blocks.append(dict(key="lead", text=p["lead"], x=72, w=1140,
                           size=26, min=22, ls=1.4, gap=18))
    if _plain(p, "body"):
        blocks.append(dict(key="body", text=p["body"], x=72, w=1140,
                           size=23, min=22, ls=1.45, gap=14))
    laid = flow(blocks, TOP, 300)

    card_y, card_h, card_w, card_gap = 308, 356, 360, 28
    IMG_H = 176
    elements = [_bar(TOP, 48, t)]
    for block, item in zip(blocks, laid):
        key, box, size = block["key"], item["box"], item["size"]
        color = t["deep"] if key == "title" else (t["mid"] if key == "lead" else t["ink"])
        elements.append(_t(key, key, box, size, color,
                           bold=(key == "title"), ls=block["ls"]))

    for index, text in enumerate(items):
        col_x = M + index * (card_w + card_gap)
        elements.append(_s("rounded", {"x": col_x, "y": card_y, "w": card_w,
                                       "h": card_h}, t["light"]))
        ib = imgs[index]["box"]
        ib.update({"x": col_x + 12, "y": card_y + 12, "w": card_w - 24, "h": IMG_H})
        elements.append(imgs[index])
        ty = card_y + 12 + IMG_H + 14
        inner_box, inner_size = autosize(text, col_x + 24, ty, card_w - 48,
                                         card_h - (ty - card_y) - 14, 23, 21, 1.42)
        elements.append(_t("item.%d" % index, "item", inner_box, inner_size,
                           t["cardInk"], ls=1.42))

    return {"layout": "authored_canvas",
            "visualPlan": _plan("evidence", note, {"type": "solid", "color": t["paper"]},
                                elements)}


# ══════════════════════════════════════════════════════════════════
# 8. 步骤流程（实验步骤 / 生长变化）
# ══════════════════════════════════════════════════════════════════
@template("steps", ("title", "lead", "body", "items"), intent="sequence", label="步骤流程",
          rationale="纵向流程页：左侧一条浅绿脊线串起各步节点，圆点按顺序由浅到深；"
                    "每步一行文字，序号写在正文里，阅读动线自上而下。")
def tpl_steps(p, t, note):
    items = [_item_text(i) for i in (p.get("items") or [])]
    if not 2 <= len(items) <= 6:
        raise LayoutError("steps 需要 2–6 条 items（当前 %d 条）" % len(items))
    imgs = _images(p)
    if imgs and len(imgs) != 1:
        raise LayoutError("steps 最多挂 1 张配图，当前 %d 张" % len(imgs))
    has_img = bool(imgs)
    text_w = 760 if has_img else 1050     # 有图时正文收窄，右侧让给配图

    blocks = [dict(key="title", text=p["title"], x=104, w=1100,
                   size=44, min=42, ls=1.15, gap=0)]
    if _plain(p, "lead"):
        blocks.append(dict(key="lead", text=p["lead"], x=72, w=(812 if has_img else 1140),
                           size=26, min=22, ls=1.4, gap=20))
    if _plain(p, "body"):
        blocks.append(dict(key="body", text=p["body"], x=72, w=(812 if has_img else 1140),
                           size=24, min=22, ls=1.45, gap=16))
    for index, text in enumerate(items):
        blocks.append(dict(key="item.%d" % index, text=text,
                           x=(152 if not has_img else 152), w=text_w,
                           size=25, min=22, ls=1.4, gap=26 if index == 0 else 22))
    laid = flow(blocks, TOP, BOTTOM)

    elements = [_bar(TOP, 48, t)]
    step_boxes = []
    for block, item in zip(blocks, laid):
        key, box, size = block["key"], item["box"], item["size"]
        if key.startswith("item."):
            step_boxes.append((box, size))
            elements.append(_t(key, "item", box, size, t["ink"], ls=1.4))
        elif key == "title":
            elements.append(_t("title", "title", box, size, t["deep"], True, 1.15))
        elif key == "body":
            elements.append(_t("body", "body", box, size, t["ink"], ls=1.45))
        else:
            elements.append(_t("lead", "lead", box, size, t["mid"], ls=1.4))

    if step_boxes:
        spine_x = 100
        spine_top = step_boxes[0][0]["y"] + 8
        spine_bottom = step_boxes[-1][0]["y"] + 8
        elements.append(_s("rect", {"x": spine_x, "y": spine_top, "w": 2,
                                    "h": max(2, spine_bottom - spine_top)},
                           t["light"]))
        for index, (box, size) in enumerate(step_boxes):
            elements.append(_dot(spine_x - 7, box["y"] + int((size * LINE_FACTOR - 16) / 2),
                                 16, t["deep"] if index == 0 else t["accent"]))

    if has_img:
        ib = imgs[0]["box"]
        ib.update({"x": 950, "y": 214, "w": 258, "h": 258})
        elements.append(imgs[0])

    return {"layout": "authored_canvas",
            "visualPlan": _plan("sequence", note, {"type": "solid", "color": t["paper"]},
                                elements)}


# ══════════════════════════════════════════════════════════════════
# 9. 结论条（课堂总结）
# ══════════════════════════════════════════════════════════════════
@template("conclusion", ("title", "lead", "summary", "body", "items"), intent="summary",
          label="结论条",
          rationale="总结页用深色结论条把本课核心结论从正文中拎出来形成视觉重心，"
                    "正文解释其含义，课后任务用小圆点并列收尾，与前页卡片语言保持一致。")
def tpl_conclusion(p, t, note):
    pad = 24
    size = 32
    blocks = [dict(key="title", text=p["title"], x=104, w=1100,
                   size=44, min=42, ls=1.15, gap=0)]
    if _plain(p, "lead"):
        blocks.append(dict(key="lead", text=p["lead"], x=72, w=1140,
                           size=27, min=22, ls=1.4, gap=22))
    if _plain(p, "summary"):
        blocks.append(dict(key="summary", text=p["summary"], x=72, w=1140,
                           size=size, min=24, ls=1.3, gap=26, padding=pad))
    if _plain(p, "body"):
        blocks.append(dict(key="body", text=p["body"], x=72, w=1140,
                           size=25, min=22, ls=1.5, gap=24))
    items = [_item_text(i) for i in (p.get("items") or [])]
    for index, text in enumerate(items):
        blocks.append(dict(key="item.%d" % index, text=text, x=108, w=1100,
                           size=24, min=22, ls=1.35, gap=24 if index == 0 else 16))
    laid = flow(blocks, TOP, BOTTOM)

    elements = [_bar(TOP, 48, t)]
    for block, item in zip(blocks, laid):
        key, box, size = block["key"], item["box"], item["size"]
        if key == "title":
            elements.append(_t("title", "title", box, size, t["deep"], True, 1.15))
        elif key == "lead":
            elements.append(_t("lead", "lead", box, size, t["mid"], ls=1.4))
        elif key == "body":
            elements.append(_t("body", "body", box, size, t["ink"], ls=1.5))
        elif key == "summary":
            elements.append(_t("summary", "summary", box, size, t["white"], True, 1.3,
                               fill=t["deep"], fillOpacity=100, rounded=True,
                               radius=0.06, padding=pad))
        else:
            last = key == "item.%d" % (len(items) - 1)
            elements.append(_dot(76, box["y"] + int((size * LINE_FACTOR - 14) / 2), 14,
                                 t["gold"] if last else t["accent"]))
            elements.append(_t(key, "item", box, size, t["ink"], ls=1.35))

    return {"layout": "authored_canvas",
            "visualPlan": _plan("summary", note, {"type": "solid", "color": t["paper"]},
                                elements)}


# ══════════════════════════════════════════════════════════════════
# 10. 配对活动（希沃原生组件，页面保持空白）
# ══════════════════════════════════════════════════════════════════
@template("match", (), intent="interaction", label="配对活动",
          rationale="互动页由希沃配对组件独占，页面不排任何文字与背景（组件页必须保持空白）。")
def tpl_match(p, t, note):
    pairs = p.get("pairs") or []
    clean = []
    for pair in pairs:
        if isinstance(pair, dict) and pair.get("left") and pair.get("right"):
            clean.append({"left": str(pair["left"]).strip(),
                          "right": str(pair["right"]).strip()})
    if len(clean) < 3:
        raise LayoutError("match 至少需要 3 组 pairs，当前 %d 组" % len(clean))
    return {"layout": "activity_page",
            "activity": {"activityType": "match", "pairs": clean}}


# ── 对外接口 ───────────────────────────────────────────────────────
def build_page(page, theme):
    """把一个简报页编译成技能可消费的页面对象。"""
    name = str(page.get("layout") or "").strip()
    if name not in TEMPLATES:
        raise LayoutError("未知版式 %r；可用：%s"
                          % (name, "、".join(sorted(TEMPLATES))))
    fn = TEMPLATES[name]
    slots = set(fn.slots)
    content = {key: page[key] for key in slots if page.get(key) not in (None, "", [])}
    if page.get("title") and "title" not in content:
        content["title"] = page["title"]      # match 等组件页不排标题，但页面仍要有标题
    if "title" not in content:
        raise LayoutError("版式 %s 必须有 title" % name)
    for key in ("table", "markdown", "pairs"):
        if page.get(key):
            content[key] = page[key]
    if page.get("images"):
        content["images"] = page["images"]      # 配图由 build_page 末尾统一追加
    note = str(page.get("rationale") or fn.default_rationale).strip()
    built = fn(content, theme, note)
    # teachingIntent 决定技能的内容密度门槛（见 README 的门槛表），允许简报覆盖
    if page.get("intent"):
        intent = str(page["intent"]).strip()
        if built.get("visualPlan"):
            built["visualPlan"]["teachingIntent"] = intent
    result = {"title": str(content["title"]).strip(), "layout": built["layout"],
              "template": name}
    for key in ("lead", "body", "items", "question", "summary"):
        if content.get(key):
            result[key] = content[key]
    if page.get("anti_pattern"):
        result["anti_pattern"] = page["anti_pattern"]
    if built.get("role"):
        result["role"] = built["role"]
    if built.get("subjectTool"):
        result["subjectTool"] = built["subjectTool"]
    if built.get("activity"):
        result["activity"] = built["activity"]
    if built.get("visualPlan"):
        img_elements = [e for e in built["visualPlan"].get("elements", [])
                        if e.get("kind") == "image"]
        if page.get("images") and not img_elements:
            # 模板自己不处理配图（如 bullets / conclusion）→ 由 build_page 按
            # 简报给的 box 追加。模板已处理配图时（如 photo_pair / cover）
            # 元素里已经含有 image，不能再追加，否则同一张图会渲染两遍。
            built["visualPlan"]["elements"].extend(_images(page))
        result["visualPlan"] = built["visualPlan"]
    # 未被该版式消费的内容字段 → 显式提示，避免"写了却丢了"
    dropped = sorted(set(page) - slots - {"title", "layout", "rationale",
                                          "anti_pattern", "table", "markdown",
                                          "pairs", "intent", "images", "variant"})
    return result, dropped


if __name__ == "__main__":
    from theme import make_theme
    import json
    print("版式库模板：")
    for key in sorted(TEMPLATES):
        fn = TEMPLATES[key]
        print("  %-14s %-12s slots=%s" % (key, fn.label, "、".join(fn.slots) or "—"))
    print()
    print("色板：", json.dumps(make_theme(), ensure_ascii=False))
