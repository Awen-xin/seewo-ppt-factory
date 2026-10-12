#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""enbx_dump.py —— 把 .enbx 每页元素列出来（序号 / 类型 / 文字 / 坐标 / 已有动画）。

写动画计划（plan.json 的 match 文本）之前**必须先跑它**：
match 是子串匹配，文本写错就静默不命中；用转储出来的真实文字才可靠。

用法：
    python enbx_dump.py "课件.enbx"                    # 全部页
    python enbx_dump.py "课件.enbx" --page 5            # 只看第 5 页
    python enbx_dump.py "课件.enbx" --json dump.json    # 同时导出 JSON（给脚本吃）
    python enbx_dump.py "课件.enbx" --anim             # 只列已有动画的页
"""
import argparse
import json
import os
import re
import sys
import tempfile
import zipfile

TOP_TAGS = ("Shape", "Text", "Picture", "Group", "Video", "Table",
            "MindMap", "Audio", "Puzzle", "Chart", "Canvas")


def read(path):
    return open(path, "rb").read().decode("utf-8-sig")


def slide_order(root):
    board = read(os.path.join(root, "Board.xml"))
    ids = re.findall(r"<Item>([0-9a-fA-F\-]{8,})</Item>", board)
    sdir = os.path.join(root, "Slides")
    files = {}
    for n in os.listdir(sdir):
        if n.endswith(".xml"):
            m = re.search(r"<Id>([^<]+)</Id>", read(os.path.join(sdir, n)))
            if m:
                files[m.group(1)] = n
    out = []
    for i, s in enumerate(ids, 1):
        if s in files:
            out.append((i, files[s]))
    return out


def elements(xml):
    """返回 [(tag, block), ...]。用**顶层** <Elements>（深度配对，兼容嵌套 <Group>）。"""
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
    if e0 is None or e1 is None:
        return []
    items, i = [], e0 + 1
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
        items.append((tag, "\n".join(lines[i:j + 1])))
        i = j + 1
    return items


def g(block, tag):
    m = re.search(r"<%s>([^<]*)</%s>" % (tag, tag), block)
    return m.group(1) if m else ""


def elem_info(tag, block):
    if tag == "Picture":
        text = g(block, "PictureName")
    else:
        text = "".join(re.findall(r"<Text>([^<]*)</Text>", block))
    anims = []
    for m in re.finditer(r"<Animations>.*?</Animations>", block, re.S):
        for a in re.finditer(r"<Animation>(.*?)</Animation>", m.group(0), re.S):
            b = a.group(1)
            anims.append("%s/%s/%s" % (g(b, "Category"), g(b, "Trigger"), g(b, "Type")))
    return {
        "tag": tag,
        "text": text.strip(),
        "x": g(block, "X"), "y": g(block, "Y"),
        "w": g(block, "Width"), "h": g(block, "Height"),
        "anims": anims,
    }


def main():
    ap = argparse.ArgumentParser(description="转储 .enbx 每页元素，便于编写动画计划")
    ap.add_argument("enbx")
    ap.add_argument("--page", type=int, help="只看某一页")
    ap.add_argument("--json", help="把结果写成 JSON")
    ap.add_argument("--anim", action="store_true", help="只列已有动画的页")
    a = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="enbx_dump_")
    with zipfile.ZipFile(a.enbx) as z:
        z.extractall(tmp)

    order = slide_order(tmp)
    result = {}
    for pageno, fname in order:
        if a.page and pageno != a.page:
            continue
        xml = read(os.path.join(tmp, "Slides", fname))
        infos = [elem_info(t, b) for t, b in elements(xml)]
        tail = xml.split("</Elements>", 1)[1] if "</Elements>" in xml else ""
        orders = re.findall(r"<Item>([0-9a-f]{32})</Item>", tail)
        has_anim = any(e["anims"] for e in infos)
        if a.anim and not has_anim:
            continue
        result[pageno] = {"file": fname, "order": orders, "elements": infos}

        print("\n═══ 第 %d 页  (%s)  元素 %d 个%s ═══"
              % (pageno, fname, len(infos), "  [有序动画]" if orders else ""))
        for i, e in enumerate(infos, 1):
            label = e["text"] or "(无文字)"
            if len(label) > 46:
                label = label[:46] + "…"
            anim = ("  ⚡" + " , ".join(e["anims"])) if e["anims"] else ""
            print("  %2d. %-8s %-48s [%s,%s %sx%s]%s"
                  % (i, e["tag"], label, e["x"], e["y"], e["w"], e["h"], anim))

    if a.json:
        json.dump(result, open(a.json, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("\n已导出：%s" % a.json)

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
