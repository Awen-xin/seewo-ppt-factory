#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anim_presets.py —— 教学意图 → 动效方案（把"写课件只写内容"延伸到"只写意图"）。

定位：版式库解决「只写内容不写坐标」，本模块解决「只写教学意图不写动效」。
生成的是 seewo_build.py 能直接吃的 **group.json 片段 + anim.json 片段**。

设计前提（全部来自《希沃动效可用清单.md》的实测结论）：
  * 只有 Appearance / Disappearance / Emphasis + Trigger=Click 可用；
  * 路径 / 音效 / 自动播放不可用；
  * 「多个元素一起动」**只能**靠 <Group>（相同 Number 会被重编号，WithPrevious 会让整份课件加载失败）；
  * 强调强度只能是 Medium 或缺省。

因此本模块产出的方案里，**同一组元素永远只用一条动画**（挂在 Group 上）。

用法
────
    # 看一眼有哪些意图
    python anim_presets.py --list

    # 先转储（拿到真实文字/坐标），再按意图出方案
    python enbx_dump.py "课件.enbx" --json dump.json
    python anim_presets.py dump.json --page 2 --intent 逐条事实
    python anim_presets.py dump.json --page 5 --intent 提问→答案

    # 全自动：给整份 dump 出两个可直接喂流水线的文件
    # （**草案**：分组/次序已能直接跑，但到底"哪几块该动"仍建议按教学设计微调，
    #   例如提问框要不要一起动、末条结论要不要改成 Emphasis 闪烁）
    python anim_presets.py dump.json --auto --out-group v2/group.json --out-anim v2/anim.json
    python seewo_build.py pipeline.json

配色/版式无关——这里只谈"什么时候动、怎么动"。
"""
import argparse
import json
import os
import re
import sys

# ── 实测可用的动画（typo 即报错，不静默降级）───────────────────────────
VERIFIED = {
    "Appearance": ["RippleInEffect", "FadeIn", "JumpIn", "ScaleIn", "RotationIn",
                   "WhirlIn", "TranslateIn", "DiagonalWipeIn",
                   "RandomizedLinesInEffect", "RotationFadeIn", "WhirlFadeIn"],
    "Disappearance": ["FadeOut", "RippleOutEffect"],
    "Emphasis": ["Flicker", "Shake", "Heartbeat", "Bounce"],
}
ALL_TYPES = {t: c for c, ts in VERIFIED.items() for t in ts}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def idx_of(elems, i):
    """dump 里的元素序号（1 起）→ 下标。"""
    return i - 1


# ══════════════════════════════════════════════════════════════════════
# 元素配对检测：找出"必须一起动"的元素集合（与 enbx_anim / enbx_group 同一套启发式）
# ══════════════════════════════════════════════════════════════════════

def _bbox(e):
    x, y, w, h = _f(e["x"]), _f(e["y"]), _f(e["w"]), _f(e["h"])
    return (x, y, w, h) if None not in (x, y, w, h) else None


def detect_groups(elems):
    """从 dump 的元素表里找出应当打包成 <Group> 的元素簇。

    返回 [ {"indexes":[...], "kind":"picture|panel|marker", "label":str}, ... ]

    ⚠️ 检测顺序必须是「图片+图注 → 面板 → 小符号」：
       图注条本身就是一个 w≥300 的大 Shape，如果先跑面板检测，它会被当成"底框"，
       把图注文字吃掉 ⇒ 图片再也配不成组（P3 三张图曾因此全被漏掉）。
    已用过的元素不再复用。
    """
    used = set()
    out = []

    # ① 图片 + 图注条 + 图注文字（图注条与图同宽、贴在图下方）—— 必须先于面板
    for i, e in enumerate(elems):
        if e["tag"] != "Picture" or i in used:
            continue
        pb = _bbox(e)
        if not pb:
            continue
        px, py, pw, ph = pb
        bar = None
        for j, s in enumerate(elems):
            if j in used or j == i or s["tag"] != "Shape":
                continue
            sb = _bbox(s)
            if not sb:
                continue
            sx, sy, sw, sh = sb
            if abs(sx - px) <= 12 and abs(sw - pw) <= 24 and sy >= py + ph - 250:
                bar = j
                break
        if bar is None:
            continue
        grp = [i, bar]
        sx, sy, sw, sh = _bbox(elems[bar])
        for k, t in enumerate(elems):
            if k in used or t["tag"] != "Text" or k in grp:
                continue
            tb = _bbox(t)
            if not tb:
                continue
            # ⚠️ 图注文字必须**落在图注条内**（中心在条内）。
            #    早先写成"起点在条右侧、底边在条下方"⇒ 把页面标题、正文段落
            #    （它们也在图的上方/左侧"满足"那个宽松条件）一并吞进了图片组。
            cx, cy = tb[0] + tb[2] / 2, tb[1] + tb[3] / 2
            if sx - 8 <= cx <= sx + sw + 8 and sy - 8 <= cy <= sy + sh + 8:
                grp.append(k)
        used.update(grp)
        out.append({"indexes": [k + 1 for k in sorted(grp)], "kind": "picture",
                    "label": elems[i]["text"] or "(图)"})

    # ② 面板：大块 Shape（底框）+ 落在其内部的 Text
    for i, e in enumerate(elems):
        if e["tag"] != "Shape" or i in used:
            continue
        bb = _bbox(e)
        if not bb or bb[2] < 300 or bb[3] < 60:
            continue
        sx, sy, sw, sh = bb
        inside = []
        for j, t in enumerate(elems):
            if t["tag"] != "Text" or j in used or j == i:
                continue
            tb = _bbox(t)
            if not tb:
                continue
            tx, ty, tw, th = tb
            if (sx - 8 <= tx + tw / 2 <= sx + sw + 8
                    and sy - 8 <= ty + th / 2 <= sy + sh + 8):
                inside.append(j)
        if inside:
            grp = [i] + inside
            # 面板内部的小 Shape（内嵌卡片底、项目符号）也要跟着一起出现
            for j, s in enumerate(elems):
                if j in used or j == i or s["tag"] != "Shape":
                    continue
                sb = _bbox(s)
                if not sb:
                    continue
                if (sx - 4 <= sb[0] and sb[0] + sb[2] <= sx + sw + 4
                        and sy - 4 <= sb[1] and sb[1] + sb[3] <= sy + sh + 4):
                    grp.append(j)
            used.update(grp)
            label = (elems[inside[0]]["text"] or "")[:14]
            out.append({"indexes": [k + 1 for k in sorted(grp)], "kind": "panel",
                        "label": label or "(面板)"})

    # ③ 项目符号：小 Shape（≤20x20）+ 右侧同一水平线的 Text
    for i, e in enumerate(elems):
        if e["tag"] != "Shape" or i in used:
            continue
        sb = _bbox(e)
        if not sb or sb[2] > 20 or sb[3] > 20:
            continue
        sx, sy, sw, sh = sb
        for j, t in enumerate(elems):
            if j in used or t["tag"] != "Text" or j == i:
                continue
            tb = _bbox(t)
            if not tb:
                continue
            tx, ty = tb[0], tb[1]
            if 0 <= tx - (sx + sw) <= 60 and abs(ty - sy) <= 40:
                used.update({i, j})
                out.append({"indexes": [i + 1, j + 1], "kind": "marker",
                            "label": (t["text"] or "")[:14]})
                break
    return out


def _reading_order(elems, group):
    """按阅读顺序（上→下，再左→右）给分组排序。"""
    e = elems[group["indexes"][0] - 1]
    return (_f(e["y"]) or 0, _f(e["x"]) or 0)


def _trailing_text(elems, groups):
    """找"收尾才出现"的那一行文字：没被分组吃掉、且**整体位于所有分组下方**的最后一个 Text。

    ⚠️ 不能简单地取"最后一个自由文字"：页面上方的引导语、正文段落同样是自由文字，
       拿它们做收尾就会出现"一开始就淡入一段正文"的怪效果。
    """
    used = {i for g in groups for i in g["indexes"]}
    if not groups:
        return None
    bottoms = []
    for g in groups:
        for i in g["indexes"]:
            bb = _bbox(elems[i - 1])
            if bb:
                bottoms.append(bb[1] + bb[3])
    limit = max(bottoms) if bottoms else 0
    cands = []
    for i, e in enumerate(elems, 1):
        if i in used or e["tag"] != "Text" or not e.get("text"):
            continue
        bb = _bbox(e)
        if bb and bb[1] >= limit - 4:
            cands.append((bb[1], i))
    return max(cands)[1] if cands else None


# ══════════════════════════════════════════════════════════════════════
# 教学意图 → 方案
# ══════════════════════════════════════════════════════════════════════

def _g(groups, kind=None):
    gs = [x for x in groups if kind is None or x["kind"] == kind]
    return gs


def preset_逐条事实(elems, page, groups):
    """逐条事实 / 项目符号列表：每条（符号+文字）依次涟漪进入，收尾文字淡入。"""
    order = sorted(groups, key=lambda g: _reading_order(elems, g))
    gpage = {"page": page, "groups": []}
    apage = {"page": page, "targets": []}
    n = 0
    for g in order:
        n += 1
        gpage["groups"].append({"indexes": g["indexes"], "name": "P%d-%s" % (page, g["label"]),
                                "anim": "RippleInEffect", "category": "Appearance", "number": n})
    tail = _trailing_text(elems, groups)
    if tail:
        n += 1
        apage["targets"].append({"index": tail, "number": n, "anim": "FadeIn",
                                 "category": "Appearance", "with_marker": False})
    return gpage, apage


def preset_多图对比(elems, page, groups, kind=None):
    """多图对比：**本页所有分组**按阅读顺序（上→下、左→右）依次进入，收尾文字淡入。

    ⚠️ 不能只挑 kind=="picture" 的组：像 P11 那种"上面两条事实、下面一张配图"的页，
       只挑图片会把两条事实整个漏掉。统一按阅读顺序走，图文混排也正确。
    """
    order = sorted(groups, key=lambda g: _reading_order(elems, g))
    gpage = {"page": page, "groups": []}
    apage = {"page": page, "targets": []}
    n = 0
    for g in order:
        n += 1
        gpage["groups"].append({"indexes": g["indexes"], "name": "P%d-%s" % (page, g["label"]),
                                "anim": "RippleInEffect", "category": "Appearance", "number": n})
    tail = _trailing_text(elems, groups)
    if tail:
        n += 1
        apage["targets"].append({"index": tail, "number": n, "anim": "FadeIn",
                                 "category": "Appearance", "with_marker": False})
    return gpage, apage


def preset_流程顺序(elems, page, groups):
    """流程 / 步骤：每个节点依次跳入，节奏比涟漪更"有推进感"。"""
    order = sorted(groups, key=lambda g: _reading_order(elems, g))
    gpage = {"page": page, "groups": []}
    n = 0
    for g in order:
        n += 1
        gpage["groups"].append({"indexes": g["indexes"], "name": "P%d-%s" % (page, g["label"]),
                                "anim": "JumpIn", "category": "Appearance", "number": n})
    apage = {"page": page, "targets": []}
    tail = _trailing_text(elems, groups)
    if tail:
        n += 1
        apage["targets"].append({"index": tail, "number": n, "anim": "FadeIn",
                                 "category": "Appearance", "with_marker": False})
    return gpage, apage


def preset_提问答案(elems, page, groups, hide_question=True):
    """提问 → 答案：内容/答案面板依次进入 → 收起提问框 → 归纳文字淡入。

    这是"探究课"最常用的节奏（第 5/6/9/10 课都是它）。
    面板数 ≥2 时，**最上面那个**（阅读顺序第一）视为提问框，其余按阅读顺序当内容；
    只有一个面板时不收起任何东西，只让它进入。
    """
    panels = sorted([g for g in groups if g["kind"] == "panel"],
                    key=lambda g: _reading_order(elems, g))
    gpage = {"page": page, "groups": []}
    apage = {"page": page, "targets": []}
    n = 0
    q = panels[0] if (hide_question and len(panels) >= 2) else None
    content = panels[1:] if q else panels
    for g in content:                     # 内容/答案面板逐个进入
        n += 1
        gpage["groups"].append({"indexes": g["indexes"], "name": "P%d-%s" % (page, g["label"]),
                                "anim": "RippleInEffect", "category": "Appearance",
                                "number": n})
    if q is not None:                     # 讲完了收起提问框
        n += 1
        gpage["groups"].append({"indexes": q["indexes"], "name": "P%d-收起提问框" % page,
                                "anim": "FadeOut", "category": "Disappearance",
                                "number": n})
    tail = _trailing_text(elems, groups)
    if tail:
        n += 1
        apage["targets"].append({"index": tail, "number": n, "anim": "FadeIn",
                                 "category": "Appearance", "with_marker": False})
    return gpage, apage


def _preset_emphasis(elems, page, groups, match, kind, reason):
    """强调 / 警示：对匹配到的元素（优先整组）加强调动画。不改动版面。"""
    tgt = None
    for g in groups:
        if any(match in (elems[i - 1].get("text") or "") for i in g["indexes"]):
            tgt = {"index": g["indexes"][0], "with_marker": False}
            break
    if tgt is None:
        for i, e in enumerate(elems, 1):
            if match in (e.get("text") or ""):
                tgt = {"index": i, "with_marker": False}
                break
    if tgt is None:
        raise SystemExit("❌ %s：本页文字里找不到 %r，无法定位（先跑 enbx_dump.py 看真实文字）"
                         % (reason, match))
    tgt.update({"number": 1, "anim": kind, "category": "Emphasis"})
    return None, {"page": page, "targets": [tgt]}


def preset_重点强调(elems, page, groups, match):
    """重点强调 → 闪烁（Flicker）。"""
    return _preset_emphasis(elems, page, groups, match, "Flicker", "重点强调")


def preset_错误警示(elems, page, groups, match):
    """错误警示 → 抖动（Shake）。"""
    return _preset_emphasis(elems, page, groups, match, "Shake", "错误警示")


PRESETS = {
    "逐条事实": preset_逐条事实,
    "多图对比": preset_多图对比,
    "流程顺序": preset_流程顺序,
    "提问→答案": preset_提问答案,
    "重点强调": preset_重点强调,
    "错误警示": preset_错误警示,
}

PRESET_DOC = {
    "逐条事实": "项目符号/卡片逐条涟漪进入，收尾文字淡入（版式：bullets / evidence）",
    "多图对比": "每张图（含图注）按位置依次进入，收尾文字淡入（版式：cards3 / two_col）",
    "流程顺序": "步骤节点依次跳入，节奏更有推进感（版式：steps / cards3）",
    "提问→答案": "答案面板先进入 → 点下一屏收起提问框 → 归纳文字淡入（版式：evidence / two_col）",
    "重点强调": "对指定文字所在元素加「闪烁」，用于核心结论（需 --match）",
    "错误警示": "对指定文字所在元素加「抖动」，用于常见错误（需 --match）",
}

# 需要 --match 的意图
NEEDS_MATCH = {"重点强调", "错误警示"}


# ══════════════════════════════════════════════════════════════════════
# 校验：产出的方案不许踩雷
# ══════════════════════════════════════════════════════════════════════

def validate(plan):
    """检查 plan 是否只用了实测可用的动画（typo 直接报错，不静默降级）。"""
    bad = []
    for pg in plan.get("pages", []):
        for t in pg.get("targets", []):
            items = t.get("anims") or [t]
            for a in items:
                kind = a.get("anim") or a.get("type")
                cat = a.get("category") or ALL_TYPES.get(kind)
                if kind not in ALL_TYPES:
                    bad.append("未知/未验证类型 %r（第 %s 页）" % (kind, pg.get("page")))
                    continue
                if cat != ALL_TYPES[kind]:
                    bad.append("%s 属于 %s，却声明为 %s（第 %s 页）"
                               % (kind, ALL_TYPES[kind], cat, pg.get("page")))
                if (a.get("magnitude") or "Medium") != "Medium":
                    bad.append("强调强度只能是 Medium 或缺省（第 %s 页）" % pg.get("page"))
                if (a.get("trigger") or "Click") != "Click":
                    bad.append("触发只能 Click（第 %s 页）" % pg.get("page"))
        for g in pg.get("groups", []):
            if g.get("anim") and g["anim"] not in ALL_TYPES:
                bad.append("未知/未验证类型 %r（第 %s 页分组）" % (g["anim"], pg.get("page")))
    return bad


def merge_group_pages(pages):
    """把多个 (page, group_page) 收成一份 group.json 结构。"""
    return {"_note": "由 anim_presets.py 生成：多元素「一起动」靠 <Group>，不用相同 Number。",
            "pages": [p for p in pages if p and p.get("groups")]}


def merge_anim_pages(pages):
    return {"_note": "由 anim_presets.py 生成：只用 Appearance/Disappearance/Emphasis + Click。",
            "pages": [p for p in pages if p and p.get("targets")]}


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════

def _load_dump(path):
    d = json.load(open(path, encoding="utf-8-sig"))
    return {int(k): v for k, v in d.items()}


def build_for_page(elems, page, intent, match=None, hide_question=True):
    groups = detect_groups(elems)
    fn = PRESETS[intent]
    if intent in NEEDS_MATCH:
        if not match:
            raise SystemExit("❌ 意图「%s」需要 --match 指定要强调的文字片段" % intent)
        return fn(elems, page, groups, match)
    if intent == "提问→答案":
        return fn(elems, page, groups, hide_question=hide_question)
    return fn(elems, page, groups)


def main():
    ap = argparse.ArgumentParser(description="教学意图 → 动效方案（group.json + anim.json 片段）")
    ap.add_argument("dump", nargs="?", help="enbx_dump.py --json 的产物")
    ap.add_argument("--list", action="store_true", help="列出可用意图")
    ap.add_argument("--page", type=int, help="只处理这一页")
    ap.add_argument("--intent", choices=list(PRESETS), help="教学意图")
    ap.add_argument("--match", help="重点强调/错误警示 要定位的文字片段")
    ap.add_argument("--keep-question", action="store_true",
                    help="提问→答案：不收起提问框")
    ap.add_argument("--auto", action="store_true",
                    help="整份 dump 自动推断意图（有图→多图对比，有面板→提问→答案，否则逐条事实）")
    ap.add_argument("--out-group", help="写出 group.json")
    ap.add_argument("--out-anim", help="写出 anim.json")
    ap.add_argument("--json", action="store_true", help="把方案打到 stdout（JSON）")
    a = ap.parse_args()

    if a.list or not a.dump:
        print("可用教学意图：\n")
        for k, v in PRESET_DOC.items():
            print("  %-8s %s" % (k, v))
        print("\n用法：python anim_presets.py dump.json --page 2 --intent 逐条事实")
        print("      python anim_presets.py dump.json --auto --out-group g.json --out-anim a.json")
        return 0

    dump = _load_dump(a.dump)
    pages = [a.page] if a.page else sorted(dump)
    gpages, apages = [], []

    for pno in pages:
        if pno not in dump:
            print("  [跳过] dump 里没有第 %s 页" % pno)
            continue
        elems = dump[pno]["elements"]
        groups = detect_groups(elems)
        if a.auto:
            has_pic = any(g["kind"] == "picture" for g in groups)
            has_panel = any(g["kind"] == "panel" for g in groups)
            intent = "多图对比" if has_pic else ("提问→答案" if has_panel else "逐条事实")
        else:
            intent = a.intent or "逐条事实"
        match = a.match
        if a.auto and intent == "逐条事实" and not groups:
            print("  [跳过] 第 %s 页没检测到可分组元素" % pno)
            continue
        g, an = build_for_page(elems, pno, intent, match=match,
                               hide_question=not a.keep_question)
        if g:
            gpages.append(g)
        if an:
            apages.append(an)
        nsteps = len([1 for gg in (g or {}).get("groups", [])]) + \
                 sum(len(t.get("anims") or [t]) for t in (an or {}).get("targets", []))
        print("  第 %-3s 页  意图=%-6s  分组 %s 组  动画 %s 步"
              % (pno, intent, len((g or {}).get("groups", [])), nsteps))

    gj = merge_group_pages(gpages)
    aj = merge_anim_pages(apages)
    bad = validate(aj)
    if bad:
        print("\n❌ 方案校验失败：")
        for b in bad:
            print("   - " + b)
        return 1
    print("\n✅ 方案校验通过（只用 Appearance/Disappearance/Emphasis + Click，无 Large）")

    if a.out_group:
        json.dump(gj, open(a.out_group, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("   已写 %s（%d 页）" % (a.out_group, len(gj["pages"])))
    if a.out_anim:
        json.dump(aj, open(a.out_anim, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("   已写 %s（%d 页）" % (a.out_anim, len(aj["pages"])))
    if a.json or (not a.out_group and not a.out_anim):
        print(json.dumps({"group": gj, "anim": aj}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
