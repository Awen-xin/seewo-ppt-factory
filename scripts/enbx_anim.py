#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""enbx_anim.py v3 — 给希沃 .enbx 课件的元素注入动画（进入 / 退出 / 强调）。

背景：希沃 MCP 的 61 个工具没有任何动画写入能力；但 enbx 的 Slide XML 支持
元素内嵌 <Animations> 节点 + 页面级 <AnimationOrders> 索引。本脚本直接在
enbx 上做后处理，把动画写进 XML，再以「本地课件」方式打开，效果与在客户端
手工添加动画完全一致。

═══ 能力边界（2026-10-10 实测；完整清单见《希沃动效可用清单.md》）═══
类别 Category：
  ✅ Appearance     进入（点击后出现）
  ✅ Disappearance  退出（点击后消失）
  ✅ Emphasis       强调
  ❌ Path           路径 —— 客户端会把它改写回 Appearance（不支持）
触发 Trigger：
  ✅ Click          点击（唯一稳定可用）
  ❌ WithPrevious   ❗会让**整份课件加载失败**（实测 slideCount=1，页面全丢）
  ❌ AutoPlay / AfterPrevious —— 客户端一律改写回 Click（即不支持自动播放）
音效：
  ❌ 不支持（<Audio>/<Sound>/<SoundEffect> 等字段被静默丢弃）
分组（多个元素一次点击同时出现）：
  ✅ 唯一可行写法 = 把元素包进 <Group>，只给 Group 挂动画
     → 用 enbx_group.py（或 seewo_build.py 的 group 阶段）
  ❌ 给多个元素写相同 <Number> —— 客户端会**顺序重编号**而失效
     （实测 1,1,2,2,3,3 → 1..6，一次点击只出一个元素）
强调类取值：
  ✅ <Magnitude>Medium</Magnitude>（或省略，客户端自动补 Medium）
  ❌ <Magnitude>Large</Magnitude> ❗同样会让**整份课件加载失败**
  ✅ <Frequency>n</Frequency> 改大安全

动画节点字段（实测自客户端回写后的真实课件，勿改字段集）：
    <Animations>
      <Animation>
        <Type>RippleInEffect</Type>       # 动画类型，见 TYPES
        <Id>32位hex</Id>
        <Number>1</Number>                # 本页第几次点击，从 1 递增（客户端会重编号）
        <Category>Appearance</Category>   # Appearance / Disappearance / Emphasis
        <Trigger>Click</Trigger>          # 点击触发
        <TriggerSource></TriggerSource>
        <Duration>3000000</Duration>      # TimeSpan ticks，3e6 = 0.3s
        <Delay>0</Delay>
        <AccelerationRatio>0</AccelerationRatio>
        <DecelerationRatio>0</DecelerationRatio>
        <RepeatBehavior>1</RepeatBehavior>
        <Start>1</Start><End>0</End>      # 进入/退出类需要（强调类不要，见下）
        <Magnitude>Medium</Magnitude>     # 仅强调类；客户端会补默认值
        <Frequency>1</Frequency>          # 仅强调类
      </Animation>
    </Animations>

用法：
    python enbx_anim.py --enbx in.enbx --plan plan.json --out out.enbx
                        [--dry-run] [--list] [--open] [--sync]

plan.json：
    {
      "pages": [
        {"page": 5, "targets": [
            {"match": "我发现", "anim": "RippleInEffect"},                   # 默认进入
            {"match": "答：",   "anim": "FadeIn", "duration": 5000000},
            {"match": "重点",   "anim": "Flicker",  "category": "Emphasis"},
            {"match": "旧结论", "anim": "FadeOut",  "category": "Disappearance"},
            {"match": "先出现", "anims": [                                   # 同元素两个动画
                {"anim": "FadeIn",  "category": "Appearance"},
                {"anim": "Flicker", "category": "Emphasis"}]}                # ❌ 别写 magnitude=Large
        ]}
      ]
    }
    match：在该页元素文字里做子串匹配（也支持 Picture 的 <PictureName>）
    index：直接按「该页第 n 个元素（1 起）」定位
           ⚠️ 分组后同页元素数会变、index 整体位移 ⇒ 分组过的页请一律用 match
    number：显式指定点击步号（与 enbx_group 写下的 Group 动画步号衔接时用）
    group：同名字的 target 共用步号。注意这只是"写相同 Number"，实测会被客户端
           重编号 ⇒ **不能**用来做"一次点击多元素同时动"；那种需求请用
           enbx_group.py 打包成 <Group>。
    anims：一个元素挂多个动画（进入 + 强调），按顺序各占一次点击
    可选字段：duration（ticks）/ delay / repeat / trigger / magnitude / frequency
             ⚠️ magnitude 只能 Medium 或缺省；Large 会让整份课件加载失败
    with_caption（默认 true）：动图片时自动带上图注条与图注文字（同样靠相同 Number，
             会被重编号 ⇒ 想真正"一起动"请改走 enbx_group.py）
    with_marker（默认 true）：动文字时自动带上左侧的小圆点/方块符号（同上）
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
import zipfile

TOP_TAGS = ("Shape", "Text", "Picture", "Group", "Video", "Table",
            "MindMap", "Audio", "Puzzle", "Chart", "Canvas")

# 类别 → 类型（verified=客户端回读中确认存活；unverified=名字来自 DLL/样本，未验证）
TYPES = {
    "Appearance": {
        "verified": {
            "RippleInEffect": "涟漪进入",
            "FadeIn": "淡入",
            "JumpIn": "跳入",
            "ScaleIn": "缩放进入",
            "RotationIn": "旋转进入",
            "WhirlIn": "回旋进入",
            "TranslateIn": "平移进入",
            "DiagonalWipeIn": "对角线擦除进入",
            "RandomizedLinesInEffect": "随机线条进入",
            "RotationFadeIn": "旋转淡入",
            "WhirlFadeIn": "回旋淡入",
        },
        "unverified": ["BlindIn", "DiamondIn", "DissolveInEffect", "DotIn", "DoubleWipeIn",
                       "DownfallInEffect", "FireWorksInEffect", "ScrollInEffect", "SpiralScaleIn",
                       "StacksInEffect", "StarIn", "SwirlInEffect", "TranslateFadeIn", "WipeDropIn"],
    },
    "Disappearance": {
        "verified": {
            "FadeOut": "淡出",
            "RippleOutEffect": "涟漪退出",
        },
        "unverified": ["BlindOut", "DiamondOut", "DissolveOutEffect", "DotOut", "DoubleWipeOut",
                       "JumpOut", "RotationOut", "RotationScaleOut", "RotationWipeOut", "StarOut",
                       "SwirlOutEffect", "TranslateFadeOut", "TranslateOut", "WaveOutEffect",
                       "WhirlFadeOut", "WhirlOut", "DownfallOut"],
    },
    "Emphasis": {
        "verified": {
            "Flicker": "闪烁",
            "Shake": "抖动",
            "Heartbeat": "心跳",
            "Bounce": "弹跳",
        },
        "unverified": ["Wave", "Explosion", "Star", "Fire", "Dot", "Change", "RotationEmphasis"],
    },
}

TRIGGERS = {
    "Click": "点击触发（已验证）",
    "WithPrevious": "与上一动画同时（用于分组；未验证）",
    "AfterPrevious": "上一动画之后（实测被改写为 Click）",
    "AutoPlay": "自动播放（实测被改写为 Click，不可用）",
}
TRIGGER = "Click"          # 默认；plan 里可用 "trigger" 覆盖

# 各「进入/退出」类型的附加字段（严格照抄实测样本）
EXTRA = {
    "RippleInEffect": "<Start>1</Start><End>0</End>",
    "FadeIn": "<Start>0</Start><End>1</End>",
    "FadeOut": "<Start>1</Start><End>0</End>",
    "RippleOutEffect": "<Start>0</Start><End>1</End>",
    "RandomizedLinesInEffect": "<Start>1</Start><End>0</End><Direction>Horizontal</Direction>",
    "JumpIn": "<Orientation>LeftToRight</Orientation>",
    "DiagonalWipeIn": "<Orientation>LeftToRight</Orientation><Effect>In</Effect><AnimationSequence>AsOneObject</AnimationSequence>",
}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def read(path):
    return open(path, "rb").read().decode("utf-8-sig")


def write(path, text):
    open(path, "wb").write(text.encode("utf-8"))


def slide_order(root):
    """按 Board.xml 给出的顺序返回 [(页序1起, 文件名), ...]。"""
    board = read(os.path.join(root, "Board.xml"))
    ids = re.findall(r"<Item>([0-9a-fA-F\-]{8,})</Item>", board)
    sdir = os.path.join(root, "Slides")
    files = {}
    for n in os.listdir(sdir):
        if n.endswith(".xml"):
            sid = re.search(r"<Id>([^<]+)</Id>", read(os.path.join(sdir, n)))
            if sid:
                files[sid.group(1)] = n
    return [(i, files[s]) for i, s in enumerate(ids, 1) if s in files]


def elements_span(xml):
    """定位**顶层** <Elements>…</Elements> 的行号 (e0, e1)，返回 (e0, e1, lines)。

    ⚠️ 不能取「第一个 <Elements> / 第一个 </Elements>」：`<Group>` 内部会再嵌一层
    `<Elements>`，于是第一个 `</Elements>` 是**组内那层**，会把后续所有处理（动画注入、
    AnimationOrders 定位）全切错——实测生成出的 XML 不合法、客户端直接拒载。
    必须按标签深度配对。
    """
    lines = xml.split("\n")
    depth = 0
    e0 = e1 = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s == "<Elements>":
            if depth == 0 and e0 is None:
                e0 = i
            depth += 1
        elif s == "</Elements>":
            depth -= 1
            if depth == 0:
                e1 = i
                break
    return e0, e1, lines


def top_elements_end(xml):
    """返回**顶层** </Elements> 结束位置的字符偏移（同样按深度配对）。"""
    depth = 0
    for m in re.finditer(r"</?Elements>", xml):
        if m.group(0) == "<Elements>":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return m.end()
    return -1


def split_elements(xml):
    """把顶层 <Elements> 拆成 [(start, end, tag, block), ...]（深度配对，兼容 <Group>）。"""
    e0, e1, lines = elements_span(xml)
    if e0 is None or e1 is None:
        return [], e0, e1, lines
    items = []
    i = e0 + 1
    while i < e1:
        m = re.match(r"^(\s*)<(%s)(\s|>)" % "|".join(TOP_TAGS), lines[i])
        if not m:
            i += 1
            continue
        indent, tag = m.group(1), m.group(2)
        j = i + 1
        while j < e1 and lines[j].rstrip() != indent + "</%s>" % tag:
            j += 1
        if j >= e1:
            i += 1
            continue
        items.append((i, j, tag, "\n".join(lines[i:j + 1])))
        i = j + 1
    return items, e0, e1, lines


def elem_text(block):
    m = re.search(r"<PictureName>([^<]*)</PictureName>", block)
    if m:
        return m.group(1)
    return "".join(re.findall(r"<Text>([^<]*)</Text>", block))


# 可以承载动画的元素类型：文字/图片，以及打包后的 Group（分组后原 Text 会藏进 Group）。
ANIM_TAGS = ("Text", "Picture", "Group")


def elem_dim(block, tag):
    m = re.search(r"<%s>([^<]*)</%s>" % (tag, tag), block)
    try:
        return float(m.group(1))
    except Exception:
        return None


def caption_siblings(items, pic, used):
    """图片底部的图注条（Shape）与图注文字（Text）要跟图片一起出现。
    图注文字被希沃加了 +8px 文本内边距，所以容差放宽到 12px / 24px。"""
    x = elem_dim(pic[3], "X"); w = elem_dim(pic[3], "Width")
    y = elem_dim(pic[3], "Y"); h = elem_dim(pic[3], "Height")
    if None in (x, w, y, h):
        return []
    out = []
    for it in items:
        if it is pic or id(it) in used or it[2] not in ("Shape", "Text"):
            continue
        ex = elem_dim(it[3], "X"); ew = elem_dim(it[3], "Width"); ey = elem_dim(it[3], "Y")
        if None in (ex, ew, ey):
            continue
        if abs(ex - x) <= 12 and abs(ew - w) <= 24 and ey >= y + h - 250:
            out.append(it)
    return out


def marker_siblings(items, txt, used):
    """文字前的小圆点/小方块符号（15x15 那类）要跟文字一起出现。
    实测样本：Shape [76,398 15x15] + Text [112,398 …] —— 同一水平线、左侧 21px。"""
    x = elem_dim(txt[3], "X"); y = elem_dim(txt[3], "Y")
    if x is None or y is None:
        return []
    out = []
    for it in items:
        if it is txt or id(it) in used or it[2] != "Shape":
            continue
        sx = elem_dim(it[3], "X"); sy = elem_dim(it[3], "Y")
        sw = elem_dim(it[3], "Width"); sh = elem_dim(it[3], "Height")
        if None in (sx, sy, sw, sh):
            continue
        if sw <= 20 and sh <= 20 and 0 <= x - (sx + sw) <= 60 and abs(sy - y) <= 40:
            out.append(it)
    return out


def elem_center(block):
    """元素的中心点；对 <Group> 取**组自身**的 X/Y/Width/Height（不是第一个子元素）。"""
    lines = block.split("\n")
    i0, i1 = group_outer_span(block) if lines and lines[0].strip().startswith("<Group") else (0, len(lines) - 1)
    seg = "\n".join(lines[i0:i1 + 1])
    g = lambda t: re.search(r"<%s>([^<]*)</%s>" % (t, t), seg)
    try:
        x = float(g("X").group(1)); y = float(g("Y").group(1))
        w = float(g("Width").group(1)); h = float(g("Height").group(1))
        return round(x + w / 2, 1), round(y + h / 2, 1)
    except Exception:
        return 0, 0


def group_outer_span(block):
    """返回 Group 块中「组自身属性区」的起止行号 (i0, i1)。

    ⚠️ 必须跳过内嵌的 <Elements>…</Elements>：Group 的 <X>/<Y>/<Width>/… 与
    <CanClone> 都在**组内元素之后**，直接对整块做正则搜索会先撞上子元素的
    同名字段（把动画插到子元素里 → 组内某个孩子单独动，整组不动）。
    """
    lines = block.split("\n")
    depth = 0
    i1 = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s == "<Elements>":
            depth += 1
        elif s == "</Elements>":
            depth -= 1
            if depth == 0:
                i1 = i
                break
    return (i1 + 1 if i1 is not None else 0), len(lines) - 1


def _set_first_tag(block, tag, value):
    """把 (i0,i1) 范围内第一个 <tag>…</tag> 换成新值。"""
    i0, i1 = group_outer_span(block)
    lines = block.split("\n")
    for i in range(i0, i1 + 1):
        m = re.match(r"^(\s*)<%s>[^<]*</%s>\s*$" % (tag, tag), lines[i])
        if m:
            lines[i] = "%s<%s>%s</%s>" % (m.group(1), tag, value, tag)
            return "\n".join(lines)
    return block


def _insert_anim(block, anim_xml, tag):
    """把 <Animations> 块插进元素内 —— 契约：插在 <CanClone> 之后
    （缺 <CanClone> 时退回 <Id> 之后）。返回新块；找不到插入点返回 None。

    ⚠️ 对 <Group> 必须只在**组自身属性区**里找锚点：整块正则搜索会先撞上
    子元素（子元素同样有 <Id>/<CanClone>），那会把动画挂到某个孩子身上，
    表现为「组内单个元素动、其余不动」。这正是分组后 match 失效的下一层坑。
    """
    head_outer = block.split("\n")[0].strip().startswith("<Group")
    lines = block.split("\n")
    i0, i1 = group_outer_span(block) if head_outer else (0, len(lines) - 1)
    for anchor in ("CanClone", "Id"):
        for i in range(i0, i1 + 1):
            if re.match(r"^\s*<%s>.*?</%s>\s*$" % (anchor, anchor), lines[i]):
                indent = re.match(r"^(\s*)", lines[i]).group(1)
                # anims_block 自身带 8 空格基准缩进；这里按锚点行的缩进重排，
                # 保证 <Animations> 与 <CanClone>/<Id> 同级（客户端按同级解析）。
                raw = [ln[8:] if ln.startswith(" " * 8) else ln for ln in anim_xml.split("\n")]
                ins = [indent + ln if ln.strip() else ln for ln in raw]
                lines[i + 1:i + 1] = ins
                return "\n".join(lines)
    return None


def resolve_category(kind, category):
    """没显式给 category 时，按类型名猜。"""
    if category:
        return category
    for cat, d in TYPES.items():
        if kind in d["verified"] or kind in d["unverified"]:
            return cat
    return "Appearance"


def check_supported(kind, category, strict=False):
    if category == "Path":
        raise SystemExit("❌ Path（沿路径移动）经实测**不被客户端支持**："
                         "客户端会把 <Category>Path</Category> 改写回 Appearance。")
    if category not in TYPES:
        raise SystemExit("未知类别 %s，可选：%s" % (category, ", ".join(TYPES)))
    d = TYPES[category]
    if kind not in d["verified"] and kind not in d["unverified"]:
        raise SystemExit("类别 %s 下未登记类型 %s\n  已验证：%s\n  未验证：%s"
                         % (category, kind, ", ".join(d["verified"]), ", ".join(d["unverified"])))
    return kind in d["verified"]


def one_anim(kind, number, category, trigger="Click", duration=3000000,
             delay=0, repeat=1, center=None, magnitude=None, frequency=None):
    if kind == "ScaleIn":
        cx, cy = center or (0, 0)
        extra = "<Center>%s,%s</Center><StartSize>0,0</StartSize><EndSize>1,1</EndSize>" % (cx, cy)
    elif kind == "RotationIn":
        cx, cy = center or (0, 0)
        extra = "<Center>%s,%s</Center><Start>0</Start><End>360</End>" % (cx, cy)
    elif category == "Emphasis":
        # 强调类：客户端自己会补 <Magnitude>Medium</Magnitude><Frequency>1</Frequency>。
        # ⚠️ 实测 <Magnitude>Large</Magnitude> 会让**整份课件加载失败**
        #    （Frequency 改大可接受）。所以只放行 Medium。
        mag = (magnitude or "Medium")
        if mag != "Medium":
            raise SystemExit("❌ 强调强度 Magnitude=%s 实测会让整份课件加载失败；"
                             "目前只验证过 Medium（可省略）。" % mag)
        extra = "<Magnitude>%s</Magnitude><Frequency>%d</Frequency>" % (mag, int(frequency or 1))
    else:
        extra = EXTRA.get(kind, "")
    extra_line = ("          %s\n" % extra) if extra else ""
    return """<Animation>
          <Type>%s</Type>
          <Id>%s</Id>
          <Number>%d</Number>
          <Category>%s</Category>
          <Trigger>%s</Trigger>
          <TriggerSource></TriggerSource>
          <Duration>%d</Duration>
          <Delay>%d</Delay>
          <AccelerationRatio>0</AccelerationRatio>
          <DecelerationRatio>0</DecelerationRatio>
          <RepeatBehavior>%d</RepeatBehavior>
%s        </Animation>""" % (kind, uuid.uuid4().hex, number, category, trigger,
                             duration, delay, repeat, extra_line)


def anims_block(anims, center=None):
    """一个元素的 <Animations> 块（可含多个 <Animation>）。返回 (xml, [动画Id,...])。"""
    parts, ids = [], []
    for a in anims:
        kind = a.get("anim") or a.get("type") or "RippleInEffect"
        cat = resolve_category(kind, a.get("category"))
        check_supported(kind, cat)
        trig = (a.get("trigger") or TRIGGER).strip()
        if trig not in TRIGGERS:
            raise SystemExit("未知 Trigger %s，可选：%s" % (trig, ", ".join(TRIGGERS)))
        block = one_anim(kind, int(a["_number"]), cat, trig,
                         int(a.get("duration") or 3000000),
                         int(a.get("delay") or 0),
                         int(a.get("repeat") or 1),
                         center,
                         a.get("magnitude"), a.get("frequency"))
        parts.append(block)
        ids.append(re.search(r"<Id>([0-9a-f]{32})</Id>", block).group(1))
    return "<Animations>\n        %s\n      </Animations>" % "\n        ".join(parts), ids


def _norm_target_anims(t):
    """把 target 归一成 anim 列表（每项一个 <Animation>）。"""
    if t.get("anims"):
        return [dict(x) for x in t["anims"]]
    return [{"anim": t.get("anim") or "RippleInEffect",
             "category": t.get("category"),
             "trigger": t.get("trigger"),
             "duration": t.get("duration"),
             "delay": t.get("delay"),
             "repeat": t.get("repeat"),
             "magnitude": t.get("magnitude"),
             "frequency": t.get("frequency")}]


def _resolve(items, t, used):
    if "index" in t:
        k = int(t["index"]) - 1
        if 0 <= k < len(items) and id(items[k]) not in used:
            return items[k]
        return None
    needle = str(t.get("match") or "")
    if not needle:
        return None
    # Group 优先于 Text：分组后元素被包进 <Group>，顶层不再有这些 Text，
    # 而 elem_text(Group) 会把组内所有文字拼起来 —— 直接命中 Group 才能
    # 保证「强调整组」而不是误伤组外的同名零散文字。
    for tag in ("Group", "Text", "Picture"):
        for it in items:
            if it[2] != tag or id(it) in used:
                continue
            if needle in elem_text(it[3]):
                return it
    return None


def inject_slide(xml, targets):
    """在单页 XML 上按 targets 注入动画，返回 (新xml, 命中报告)。"""
    items, e0, e1, lines = split_elements(xml)
    if not items:
        return xml, []

    report, edits, add_orders = [], [], []
    used = set()
    number = 0                 # 页面内"点击步"计数
    group_num = {}             # group 名 → 已分配的起始步号

    for t in targets:
        hit = _resolve(items, t, used)
        if not hit:
            report.append((t, None))
            continue
        used.add(id(hit))
        group_items = [hit]
        if hit[2] == "Picture" and t.get("with_caption", True):
            group_items += caption_siblings(items, hit, used)
        elif hit[2] == "Text" and t.get("with_marker", True):
            group_items += marker_siblings(items, hit, used)
        for it in group_items:
            used.add(id(it))

        anims = _norm_target_anims(t)
        gkey = (t.get("group") or "").strip()
        if t.get("number"):
            # 显式指定步号（与 enbx_group 写下的 Group 动画编号衔接时用）
            base = int(t["number"])
            number = max(number, base - 1)
        elif gkey and gkey in group_num:
            base = group_num[gkey]          # 与同组 target 共用步号（客户端可能重编）
        else:
            base = number + 1
            if gkey:
                group_num[gkey] = base
        for i, a in enumerate(anims):
            a["_number"] = base + i
        number = max(number, base + len(anims) - 1)

        try:
            for s, e, tag, block in group_items:
                cx, cy = elem_center(block)
                ax, ids = anims_block(anims, center=(cx, cy))
                blk = _insert_anim(block, ax, tag)
                if blk is None:
                    log("  [warn] 元素缺 Id，跳过：%s" % block[:60].replace("\n", " "))
                    continue
                edits.append((s, e, blk))
                for i, aid in enumerate(ids):
                    add_orders.append((base + i, aid))
            desc = "; ".join("%s/%s/%s" % (a.get("anim") or a.get("type"),
                                           resolve_category(a.get("anim") or a.get("type") or "",
                                                            a.get("category")),
                                           a.get("trigger") or TRIGGER) for a in anims)
            report.append((t, "N%s %s%s" % (base if len(anims) == 1 else "%d-%d" % (base, number),
                                            desc,
                                            " ×%d元素" % len(group_items) if len(group_items) > 1 else "")))
        except SystemExit:
            raise

    for s, e, blk in sorted(edits, key=lambda x: -x[0]):
        lines[s:e + 1] = blk.split("\n")
    xml = "\n".join(lines)

    if add_orders:
        xml = insert_orders(xml, add_orders)
    return xml, report


def anim_numbers(xml):
    """扫描页面里所有 <Animation>，返回 {动画Id: 步号}。"""
    out = {}
    for a in re.finditer(r"<Animation>(.*?)</Animation>", xml, re.S):
        b = a.group(1)
        i = re.search(r"<Id>([0-9a-f]{32})</Id>", b)
        n = re.search(r"<Number>(\d+)</Number>", b)
        if i and n:
            out[i.group(1)] = int(n.group(1))
    return out


def _orders_block(pairs):
    pairs = sorted(pairs, key=lambda x: x[0])
    return ("<AnimationOrders>\n    "
            + "\n    ".join("<Item>%s</Item>" % i for _, i in pairs)
            + "\n  </AnimationOrders>\n  ")


def insert_orders(xml, add_orders):
    """把 [(步号, 动画Id), ...] 并入页面级 <AnimationOrders>。

    关键点（踩过两次）：
      1. 必须用**顶层** </Elements> 定位 —— `<Group>` 会嵌一层 <Elements>，
         取第一个会把内容切错、生成不合法 XML，客户端直接拒载。
      2. </Duration> 要在该位置之后才搜 —— 否则会撞上动画块内部的 <Duration>。
      3. 页面**可能已经有** <AnimationOrders>（enbx_group 先跑过）⇒ 必须按步号
         **合并**成一块，不能并排插两块（两块会被客户端忽略）。
    """
    if not add_orders:
        return xml
    me_end = top_elements_end(xml)
    if me_end < 0:
        return xml
    nums = anim_numbers(xml)
    m = re.search(r"<AnimationOrders>(.*?)</AnimationOrders>", xml[me_end:], re.S)
    if m:
        pairs = list(add_orders)
        have = {aid for _, aid in pairs}
        for aid in re.findall(r"<Item>([0-9a-f]{32})</Item>", m.group(1)):
            if aid not in have:
                pairs.append((nums.get(aid, 10 ** 6), aid))
        s = me_end + m.start()
        e = me_end + m.end()
        return xml[:s] + _orders_block(pairs).rstrip() + xml[e:]
    mt = re.search(r"</Duration>\s*", xml[me_end:])
    if mt:
        pos = me_end + mt.end()
        return xml[:pos] + _orders_block(add_orders) + xml[pos:]
    return xml[:me_end] + "\n  <Duration>5000000</Duration>\n  " + _orders_block(add_orders) + xml[me_end:]


def build(enbx_in, plan, out, dry_run=False):
    tmp = tempfile.mkdtemp(prefix="enbx_anim_")
    with zipfile.ZipFile(enbx_in) as z:
        z.extractall(tmp)
        names = z.namelist()

    order = slide_order(tmp)
    by_page = {}
    for item in (plan.get("pages") or []):
        by_page[int(item["page"])] = item.get("targets") or []

    total = 0
    for pageno, fname in order:
        targets = by_page.get(pageno)
        if not targets:
            continue
        path = os.path.join(tmp, "Slides", fname)
        xml = read(path)
        new, report = inject_slide(xml, targets)
        if new != xml and not dry_run:
            write(path, new)
        hit = sum(1 for _, r in report if r)
        total += hit
        print("P%-3d %-22s 命中 %d/%d  %s"
              % (pageno, fname, hit, len(targets),
                 "; ".join("'%s'→%s" % (t.get("match") or t.get("index"), r or "✗")
                           for t, r in report)), flush=True)

    if dry_run:
        shutil.rmtree(tmp, ignore_errors=True)
        print("[dry-run] 未写出文件；共可注入 %d 个动画" % total)
        return total

    if os.path.exists(out):
        os.remove(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            p = os.path.join(tmp, n)
            if os.path.isfile(p):
                z.write(p, n)
    shutil.rmtree(tmp, ignore_errors=True)
    print("完成：%s（注入 %d 个动画）" % (out, total))
    return total


def list_types():
    for cat, d in TYPES.items():
        print("\n【%s】" % cat)
        for k, v in d["verified"].items():
            print("  ✅ %-26s %s" % (k, v))
        if d["unverified"]:
            print("  ⚠️ 未验证：%s" % ", ".join(d["unverified"]))
    print("\n【Trigger】")
    for k, v in TRIGGERS.items():
        print("  %-14s %s" % (k, v))
    print("\n【不支持】Path（沿路径移动）、音效；"
          "同组多元素写相同 Number 会被客户端重编号（改用 WithPrevious，未验证）")


def main():
    ap = argparse.ArgumentParser(description="给希沃 .enbx 注入进入/退出/强调动画")
    ap.add_argument("--enbx")
    ap.add_argument("--plan", help="动画计划 JSON")
    ap.add_argument("--out")
    ap.add_argument("--dry-run", action="store_true", help="只校验并打印，不写文件")
    ap.add_argument("--list", action="store_true", help="列出可用动画类型后退出")
    ap.add_argument("--open", action="store_true", help="生成后立刻用本地课件打开")
    ap.add_argument("--sync", action="store_true", help="打开后同步上云（走 publish_courseware.py）")
    args = ap.parse_args()

    if args.list:
        list_types()
        return
    if not (args.enbx and args.plan):
        raise SystemExit("需要 --enbx 与 --plan（或 --list）")

    plan = json.load(open(args.plan, encoding="utf-8"))
    out = args.out or args.enbx
    n = build(args.enbx, plan, out, dry_run=args.dry_run)
    if not args.dry_run and n == 0:
        raise SystemExit("没有任何动画注入成功，请检查 match 文本")

    if args.sync:
        # 统一走发布工具（含「同步后清理同名旧副本」，见 publish_courseware.py）
        here = os.path.dirname(os.path.abspath(__file__))
        pub = os.path.join(here, "publish_courseware.py")
        if not os.path.exists(pub):
            raise SystemExit("未找到 publish_courseware.py；请手动打开并同步。")
        os.system('"%s" "%s" --cleanup' % (sys.executable, pub, out))
    elif args.open:
        os.startfile(os.path.abspath(out))
        print("已打开本地课件：%s" % os.path.abspath(out))


if __name__ == "__main__":
    main()
