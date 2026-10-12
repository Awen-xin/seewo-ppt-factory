#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""enbx_group.py —— 把同一页里的多个元素打包成一个 <Group>。

为什么需要它（2026-10-10 实测）：
    客户端会按 <AnimationOrders> 把页面动画**顺序重编号**，所以「给图、图注条、
    图注文字都写 Number=1」并不等于「一次点击同时出现」——实测被改成
    1..9，一次点击只出一个元素。而 Trigger=WithPrevious 会让**整份课件加载失败**。
    ⇒ 唯一可行的「一起动」写法：把若干元素包进一个 <Group>，只给 Group 挂动画。

<Group> 结构（取自客户端缓存里的真实样本 d41b0c5c…）：
    <Group>
      <Elements>
        <Picture>…</Picture>          # 子元素坐标是**相对 Group 左上角**的
        <Text>…</Text>
      </Elements>
      <Id>32位hex</Id>
      <X>..</X><Y>..</Y><Width>..</Width><Height>..</Height>
      <Rotation>0</Rotation><IsLocked>False</IsLocked><CanClone>False</CanClone>
      <HasMask>False</HasMask><RotateOrigin>0.5,0.5</RotateOrigin>
      <SaveInfoMetadata>…</SaveInfoMetadata>
    </Group>

用法：
    python enbx_group.py --enbx in.enbx --spec group.json --out out.enbx [--dry-run]

group.json：
    { "pages": [ { "page": 3, "groups": [
        { "indexes": [6,7,8], "name": "img1", "anim": "RippleInEffect", "number": 1 },
        { "indexes": [9,10,11], "name": "img2", "anim": "RippleInEffect", "number": 2 }
      ] } ] }
    同页可有多组；indexes 是「该页第 n 个元素（1 起）」。
    给 anim/category/trigger 就会给整个 Group 挂一个动画（这是"一次点击全出"的正解）；
    number 是该页的点击步号，省略则按组序 1,2,3… 自动编。
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enbx_anim as A   # noqa: E402


def _set_tag(block, tag, value):
    """把块里第一个 <tag>…</tag> 替换成新值（只动顶层，够用）。"""
    return re.sub(r"<%s>[^<]*</%s>" % (tag, tag), "<%s>%s</%s>" % (tag, value, tag),
                  block, count=1)


def _indent(block, n=2):
    pad = " " * n
    return "\n".join(pad + ln if ln.strip() else ln for ln in block.split("\n"))


def _reindent(text, n):
    """去掉公共前导空白后统一缩进 n 个空格（保持块内相对层次）。"""
    ls = text.split("\n")
    leads = [len(l) - len(l.lstrip()) for l in ls if l.strip()]
    cut = min(leads) if leads else 0
    pad = " " * n
    return "\n".join(pad + l[cut:] if l.strip() else l for l in ls)


def make_group(blocks, gid=None, anim_clause=None):
    """blocks: 同页若干元素的 XML 文本。返回 (group_xml, bbox)。缩进以 0 为基准。"""
    xs, ys, xe, ye = [], [], [], []
    for b in blocks:
        x = A.elem_dim(b, "X"); y = A.elem_dim(b, "Y")
        w = A.elem_dim(b, "Width"); h = A.elem_dim(b, "Height")
        if None in (x, y, w, h):
            raise SystemExit("元素缺 X/Y/Width/Height，无法分组")
        xs.append(x); ys.append(y); xe.append(x + w); ye.append(y + h)
    gx, gy = min(xs), min(ys)
    gw, gh = max(xe) - gx, max(ye) - gy

    kids = []
    for b in blocks:
        x = A.elem_dim(b, "X"); y = A.elem_dim(b, "Y")
        b2 = _set_tag(_set_tag(b, "X", _num(x - gx)), "Y", _num(y - gy))
        kids.append(_reindent(b2, 4))

    ax = ("\n" + _reindent(anim_clause, 2)) if anim_clause else ""
    gid = gid or uuid.uuid4().hex
    return """<Group>
  <Elements>
%s
  </Elements>%s
  <Id>%s</Id>
  <X>%s</X>
  <Y>%s</Y>
  <Width>%s</Width>
  <Height>%s</Height>
  <Rotation>0</Rotation>
  <IsLocked>False</IsLocked>
  <CanClone>False</CanClone>
  <HasMask>False</HasMask>
  <RotateOrigin>0.5,0.5</RotateOrigin>
  <SaveInfoMetadata>
    <SupportsFallback>True</SupportsFallback>
    <ImportanceLevel>Important</ImportanceLevel>
  </SaveInfoMetadata>
</Group>""" % ("\n".join(kids), ax, gid, _num(gx), _num(gy), _num(gw), _num(gh)), (gx, gy, gw, gh)


def _num(v):
    """紧凑数字：去掉多余小数位，避免浮点噪声。"""
    return ("%.3f" % v).rstrip("0").rstrip(".") or "0"


def group_slide(xml, groups):
    """在单页 XML 上完成分组；返回 (新xml, 报告)。"""
    items, e0, e1, lines = A.split_elements(xml)
    if not items:
        return xml, []
    report = []
    edits = []          # (start, end, 新内容 或 None=删除)
    used = set()
    add_orders = []
    for n, spec in enumerate(groups, 1):
        idxs = [int(i) for i in spec["indexes"]]
        picked = []
        for i in idxs:
            if not (1 <= i <= len(items)) or i in used:
                picked = []
                break
            used.add(i)
            picked.append(items[i - 1])
        if len(picked) != len(idxs):
            report.append((spec.get("name") or idxs, None))
            continue
        picked.sort(key=lambda it: it[0])
        blocks = [b for _, _, _, b in picked]

        # 先算 bbox（Group 的绝对坐标 + 子元素相对坐标都依赖它）
        xs, ys, xe, ye = [], [], [], []
        for b in blocks:
            x = A.elem_dim(b, "X"); y = A.elem_dim(b, "Y")
            w = A.elem_dim(b, "Width"); h = A.elem_dim(b, "Height")
            if None in (x, y, w, h):
                raise SystemExit("P%d 第 %s 个元素缺 X/Y/Width/Height" % (n, idxs))
            xs.append(x); ys.append(y); xe.append(x + w); ye.append(y + h)
        gx, gy, gw, gh = min(xs), min(ys), max(xe) - min(xs), max(ye) - min(ys)

        clause = None
        if spec.get("anim") or spec.get("anims"):
            anims = A._norm_target_anims(spec)
            num = int(spec.get("number") or n)
            for i, a in enumerate(anims):
                a["_number"] = num + i
            clause, ids = A.anims_block(anims, center=(gx + gw / 2, gy + gh / 2))
            for i, aid in enumerate(ids):
                add_orders.append((num + i, aid))
            desc_anim = "+".join("%s/%s" % (a.get("anim") or a.get("type"),
                                           A.resolve_category(a.get("anim") or a.get("type") or "",
                                                              a.get("category"))) for a in anims)
        else:
            desc_anim = "无动画"

        gxml, _ = make_group(blocks, anim_clause=clause)
        # 对齐被替换元素的缩进（否则 <Group> 顶格而 </Group> 有缩进，
        # 行级配对解析会认不出它，后续动画注入/转储全会错位）
        lead = re.match(r"^(\s*)", lines[picked[0][0]]).group(1)
        if lead:
            gxml = "\n".join(lead + ln if ln.strip() else ln for ln in gxml.split("\n"))
        # 用「Group 替换第一个被选元素自身的行区间 + 删除其余元素自身的行区间」，
        # 而不是「替换 [首,尾] 整段」——否则非相邻的选取会连带吞掉中间元素。
        edits.append((picked[0][0], picked[0][1], gxml))
        for s, e, _, _ in picked[1:]:
            edits.append((s, e, None))
        report.append((spec.get("name") or idxs,
                       "%d元素→Group [%s]" % (len(picked), desc_anim)))

    # 单趟应用编辑（升序）：先复制未编辑区间，再写新内容。不能先删后替换，
    # 否则删除会让后面的行号整体偏移，替换区间就错位了。
    spans = sorted(edits, key=lambda x: x[0])
    out, cur = [], 0
    for s, e, new in spans:
        if s < cur:
            raise SystemExit("分组区间重叠（第 %d 行），请检查 indexes" % (s + 1))
        out.extend(lines[cur:s])
        if new is not None:
            out.extend(new.split("\n"))
        cur = e + 1
    out.extend(lines[cur:])
    xml = "\n".join(out)
    if add_orders:
        xml = A.insert_orders(xml, add_orders)
    return xml, report


def build(enbx_in, spec, out, dry_run=False):
    tmp = tempfile.mkdtemp(prefix="enbx_group_")
    with zipfile.ZipFile(enbx_in) as z:
        z.extractall(tmp)
        names = z.namelist()
    order = A.slide_order(tmp)
    by_page = {int(p["page"]): (p.get("groups") or []) for p in (spec.get("pages") or [])}
    total = 0
    for pageno, fname in order:
        groups = by_page.get(pageno)
        if not groups:
            continue
        path = os.path.join(tmp, "Slides", fname)
        xml = A.read(path)
        new, report = group_slide(xml, groups)
        if new != xml and not dry_run:
            A.write(path, new)
        hit = sum(1 for _, r in report if r)
        total += hit
        print("P%-3d %-20s 分组 %d/%d  %s"
              % (pageno, fname, hit, len(groups),
                 "; ".join("%s→%s" % (n, r or "✗") for n, r in report)), flush=True)
    if dry_run:
        shutil.rmtree(tmp, ignore_errors=True)
        print("[dry-run] 未写出；共 %d 组" % total)
        return total
    if os.path.exists(out):
        os.remove(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            p = os.path.join(tmp, n)
            if os.path.isfile(p):
                z.write(p, n)
    shutil.rmtree(tmp, ignore_errors=True)
    print("完成：%s（%d 组）" % (out, total))
    return total


def main():
    ap = argparse.ArgumentParser(description="把 enbx 同页多个元素打包成 Group")
    ap.add_argument("--enbx", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding="utf-8"))
    build(a.enbx, spec, a.out or a.enbx, dry_run=a.dry_run)


if __name__ == "__main__":
    main()
