#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""教材取图.py —— 从教材 PDF 批量抽插图（CMYK→RGB 存 JPG）+ 整页渲染供核对。

从一次性脚本 `_extract_pdf_imgs.py` 提升为通用工具：PDF、页码范围、输出目录全部
走命令行参数，换教材/换课不必改代码。

用法：
    python 教材取图.py --pdf <教材.pdf> --pages 27-30 --out <配图目录>
    python 教材取图.py --pdf a.pdf --pages 22,23,24-26 --out ./配图 --min-width 80
    python 教材取图.py --pdf a.pdf --pages 27-30 --out ./配图 --no-page-render

参数：
    --pdf         教材 PDF 路径（必填）
    --pages       页码范围，如 "27-30"、"22,23,25"、"22,23,24-26"（必填，1 起）
    --out         插图输出目录（必填；不存在则创建）
    --tag-prefix  文件名前缀，默认 "P"（→ P27_img1.jpg）
    --min-width   跳过宽度小于该值的细长装饰条，默认 60
    --dpi         整页渲染分辨率，默认 150
    --no-page-render  只抽插图，不做整页渲染
    --no-cmyk-fix 保留原始色彩空间（默认把 CMYK/灰度转 RGB）

依赖：pymupdf（PyMuPDF）
"""
import argparse
import io
import os
import sys


def parse_pages(text):
    """'22,23,24-26' → [22, 23, 24, 25, 26]"""
    pages = []
    for chunk in text.replace("，", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(chunk))
    return sorted(set(pages))


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="从教材 PDF 抽插图 + 整页渲染")
    ap.add_argument("--pdf", required=True, help="教材 PDF 路径")
    ap.add_argument("--pages", required=True, help="页码范围，如 27-30 或 22,23,24-26")
    ap.add_argument("--out", required=True, help="插图输出目录")
    ap.add_argument("--tag-prefix", default="P", help="文件名前缀（默认 P）")
    ap.add_argument("--min-width", type=int, default=60, help="跳过宽度更小的装饰条（默认 60）")
    ap.add_argument("--dpi", type=int, default=150, help="整页渲染 dpi（默认 150）")
    ap.add_argument("--no-page-render", action="store_true", help="不做整页渲染")
    ap.add_argument("--no-cmyk-fix", action="store_true", help="保留原始色彩空间")
    args = ap.parse_args()

    try:
        import pymupdf
    except ImportError:
        raise SystemExit("缺少 pymupdf。请安装：pip install pymupdf（或走清华镜像）")

    if not os.path.isfile(args.pdf):
        raise SystemExit("PDF 不存在：%s" % args.pdf)
    pages = parse_pages(args.pages)
    if not pages:
        raise SystemExit("页码范围解析为空：%s" % args.pages)

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    doc = pymupdf.open(args.pdf)

    saved = []
    for pno in pages:
        tag = "%s%d" % (args.tag_prefix, pno)
        page = doc[pno - 1]
        idx = 0
        for info in page.get_image_info(xrefs=True):
            xref = info.get("xref") or 0
            if not xref:
                continue
            pix = pymupdf.Pixmap(doc, xref)
            if pix.width < args.min_width:
                print("  跳过细条 %s xref=%s %dx%d" % (tag, xref, pix.width, pix.height))
                continue
            if not args.no_cmyk_fix and pix.colorspace and pix.colorspace.n in (3, 4):
                if pix.colorspace.n > 3:
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            elif not args.no_cmyk_fix and pix.colorspace and pix.colorspace.n == 1:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            idx += 1
            name = "%s_img%d.jpg" % (tag, idx)
            pix.save(os.path.join(out, name), jpg_quality=92)
            b = info["bbox"]
            saved.append(name)
            print("  保存 %-14s %dx%d  放置 box=%.0f,%.0f,%.0f,%.0f"
                  % (name, pix.width, pix.height, b[0], b[1], b[2], b[3]))

    if not args.no_page_render:
        for pno in pages:
            tag = "%s%d" % (args.tag_prefix, pno)
            pix = doc[pno - 1].get_pixmap(dpi=args.dpi)
            path = os.path.join(out, "_印刷页_%s.png" % tag)
            pix.save(path)
            print("  整页渲染 %s" % path)

    print("\n共保存插图 %d 张 → %s" % (len(saved), out))


if __name__ == "__main__":
    main()
