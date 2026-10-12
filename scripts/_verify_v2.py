#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_verify_v2.py —— 第6课 v2 最终一致性核验（本地构建 enbx vs 云端回读缓存）。

⚠️ 上一轮"页码错位"的根因：客户端缓存文件名是 `Slide_<N>_<stamp>.<rand>.xml`，
   按**文件名字典序**排会变成 Slide_0, Slide_1, Slide_10, Slide_11, ..., Slide_2
   ⇒ 页码整体乱掉。正确做法 = 读 `Board_*.xml` 的 `<Item>` 顺序，或按文件名的
   数字 N 排序（N 从 0 起，对应第 N+1 页）。

本脚本：
 1. 从本地 enbx（zip）与云端缓存目录各建「页序 → XML」映射（按 Board 顺序对齐）
 2. 深度配对解析顶层 <Elements>（兼容 <Group> 内嵌 <Elements>）
 3. 逐页比对：元素数 / 标签 / 文字 / 动画(类别/触发/类型/步号) / Group 内部元素数
 4. 汇报差异
"""
import os
import re
import sys
import zipfile
import tempfile
import shutil
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seewo_config                                     # noqa: E402

TOP_TAGS = ("Shape", "Text", "Picture", "Group", "Video", "Table",
            "MindMap", "Audio", "Puzzle", "Chart", "Canvas")


def read(p):
    return open(p, "rb").read().decode("utf-8-sig", errors="replace")


def find_one(root, name):
    """缓存目录里文件名带随机后缀；用前缀找唯一文件。"""
    hits = [f for f in os.listdir(root) if re.match(r"^%s_[0-9a-f]{4}\." % re.escape(name), f)]
    if not hits:
        hits = [f for f in os.listdir(root) if f.startswith(name + "_") or f == name]
    return os.path.join(root, hits[0]) if hits else None


def board_order(root):
    """返回 [slideId, ...]，按 Board 的 <Item> 顺序。"""
    bp = find_one(root, "Board") or os.path.join(root, "Board.xml")
    if not bp or not os.path.exists(bp):
        return None
    return re.findall(r"<Item>([0-9a-fA-F\-]{8,})</Item>", read(bp))


def slide_files(root):
    """返回 {slideId: 文件绝对路径}。"""
    sdir = os.path.join(root, "Slides")
    if not os.path.isdir(sdir):
        sdir = root
    out = {}
    for n in os.listdir(sdir):
        if not re.match(r"^Slide_\d+.*\.xml$", n):
            continue
        p = os.path.join(sdir, n)
        m = re.search(r"<Id>([^<]+)</Id>", read(p))
        if m:
            out[m.group(1)] = p
    return out


def ordered_pages(root):
    """→ [(pageNo, xml_text), ...]，严格按 Board 顺序；无 Board 时按文件名数字序。"""
    ids = board_order(root)
    files = slide_files(root)
    pages = []
    if ids:
        for i, sid in enumerate(ids, 1):
            if sid in files:
                pages.append((i, read(files[sid])))
    if not pages:
        sdir = os.path.join(root, "Slides")
        if not os.path.isdir(sdir):
            sdir = root
        names = [n for n in os.listdir(sdir) if re.match(r"^Slide_\d+.*\.xml$", n)]
        names.sort(key=lambda n: int(re.match(r"^Slide_(\d+)", n).group(1)))
        for n in names:
            k = int(re.match(r"^Slide_(\d+)", n).group(1))
            pages.append((k + 1, read(os.path.join(sdir, n))))
    return pages


def top_span(xml):
    """顶层 <Elements>...</Elements> 的行下标区间（深度配对，抗 <Group> 内嵌）。"""
    lines = xml.split("\n")
    depth, e0 = 0, None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s == "<Elements>":
            if depth == 0 and e0 is None:
                e0 = i
            depth += 1
        elif s == "</Elements>":
            depth -= 1
            if depth == 0:
                return lines, e0, i
    return lines, None, None


def split_top(xml):
    """切出顶层元素块 [(tag, block), ...]。"""
    lines, e0, e1 = top_span(xml)
    if e0 is None:
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


def anims_of(block):
    """[[(Category,Trigger,Type,Number,extra), ...]] —— 按 <Animation> 顺序。"""
    out = []
    for m in re.finditer(r"<Animations>.*?</Animations>", block, re.S):
        for a in re.finditer(r"<Animation>(.*?)</Animation>", m.group(0), re.S):
            b = a.group(1)
            extra = ""
            if "Magnitude" in b:
                extra += "Mag=" + g(b, "Magnitude")
            if "Frequency" in b and "Frequency" not in extra:
                extra += " Freq=" + g(b, "Frequency")
            out.append((g(b, "Category"), g(b, "Trigger"), g(b, "Type"),
                        g(b, "Number"), extra.strip()))
    return out


def orders_of(xml):
    """页面级 <AnimationOrders> 块数 + 每块的 Id 数（只看顶层 </Elements> 之后）。"""
    lines, e0, e1 = top_span(xml)
    tail = "\n".join(lines[e1 + 1:]) if e1 is not None else xml
    blocks = re.findall(r"<AnimationOrders>(.*?)</AnimationOrders>", tail, re.S)
    return len(blocks), [len(re.findall(r"<Item>", b)) for b in blocks]


def elem_info(tag, block):
    text = g(block, "PictureName") if tag == "Picture" else "".join(re.findall(r"<Text>([^<]*)</Text>", block))
    return {"tag": tag, "text": text.strip(), "anims": anims_of(block)}


def sub_count(block, tag):
    """统计 block 内出现多少次 <tag> 开标签（含嵌套）。"""
    return len(re.findall(r"<%s(\s|>)" % tag, block))


def summarize(pages):
    out = {}
    for pno, xml in pages:
        elems = [(t, b) for t, b in split_top(xml)]
        infos = [elem_info(t, b) for t, b in elems]
        nblocks, counts = orders_of(xml)
        is_video = "<Video>" in xml
        has_act = "<Activity>" in xml
        groups = [b for t, b in elems if t == "Group"]
        out[pno] = {
            "n_elem": len(elems),
            "elems": infos,
            "group_children": [sub_count(b, "Picture") + sub_count(b, "Text") +
                               sub_count(b, "Shape") for b in groups],
            "n_group": len(groups),
            "orders_blocks": nblocks,
            "orders_len": counts,
            "video": is_video,
            "activity": has_act,
        }
    return out


def main():
    _home = seewo_config.get_home()
    local_enbx = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        _home, "第6课-植物的繁殖", "第6课 植物的繁殖-含视频.enbx")
    cloud_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        seewo_config.get_courseware_db_dir() or "",
        "025ed309-f876-45f2-81f3-ea11992a2d7c")

    tmp = tempfile.mkdtemp(prefix="_verify_v2_")
    try:
        with zipfile.ZipFile(local_enbx) as z:
            z.extractall(tmp)
        L = summarize(ordered_pages(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not os.path.isdir(cloud_dir):
        print("❌ 云端缓存目录不存在：%s" % cloud_dir)
        return 1
    C = summarize(ordered_pages(cloud_dir))

    print("本地 enbx : %d 页" % len(L))
    print("云端回读  : %d 页" % len(C))
    print("=" * 78)

    allp = sorted(set(L) | set(C))
    diffs = 0
    for pno in allp:
        l, c = L.get(pno), C.get(pno)
        if not l or not c:
            print("P%-3d  ❌ 单边缺失 本地=%s 云端=%s" % (pno, bool(l), bool(c)))
            diffs += 1
            continue
        la = [a for e in l["elems"] for a in e["anims"]]
        ca = [a for e in c["elems"] for a in e["anims"]]
        ok = (l["n_elem"] == c["n_elem"] and la == ca and
              l["orders_blocks"] == c["orders_blocks"] and
              l["group_children"] == c["group_children"] and
              l["video"] == c["video"] and l["activity"] == c["activity"])
        flag = "✅" if ok else "⚠️"
        if not ok:
            diffs += 1
        print("%s P%-3d 元素 %d/%d  动画 %d/%d  Group %s/%s  Orders块 %s  Video %s  Activity %s"
              % (flag, pno, l["n_elem"], c["n_elem"], len(la), len(ca),
                 l["group_children"], c["group_children"],
                 "%d(%s)" % (c["orders_blocks"], c["orders_len"]), c["video"], c["activity"]))
        if not ok:
            if l["n_elem"] != c["n_elem"]:
                print("      元素数不同：本地 %d，云端 %d" % (l["n_elem"], c["n_elem"]))
            if la != ca:
                print("      动画不同：")
                print("        本地 %s" % la)
                print("        云端 %s" % ca)
            if l["group_children"] != c["group_children"]:
                print("      Group 子元素数不同：本地 %s，云端 %s"
                      % (l["group_children"], c["group_children"]))
            if l["orders_blocks"] != c["orders_blocks"]:
                print("      Orders 块数不同：本地 %d，云端 %d" % (l["orders_blocks"], c["orders_blocks"]))

    print("=" * 78)
    total_anim_l = sum(len([a for e in v["elems"] for a in e["anims"]]) for v in L.values())
    total_anim_c = sum(len([a for e in v["elems"] for a in e["anims"]]) for v in C.values())
    print("合计：本地动画 %d / 云端动画 %d ；差异页 %d" % (total_anim_l, total_anim_c, diffs))
    print("云端含视频页：%s ；含活动页：%s"
          % ([p for p, v in C.items() if v["video"]], [p for p, v in C.items() if v["activity"]]))
    if diffs == 0:
        print("\n🎉 本地构建与云端回读**逐页一致**。")
    else:
        print("\n⚠️ 存在 %d 页差异，见上。" % diffs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
