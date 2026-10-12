#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""几何自检：给一份 pages.json 做"上投影前"的体检。

    python check_geometry.py --spec ../第6课-植物的繁殖/pages.json

检查四项（都是实际会出事故的点）：
  1. 越界          —— 任何元素框超出 1280×720
  2. 压安全槽      —— 工具页元素压到原生组件安全区 y≥234（技能会直接报错）
  3. 文本压叠      —— 两个文本框在 x、y 上都真实重叠
  4. 渲染零增长    —— 文本框在渲染口径（1.42）下会不会被"偷偷撑高"
                      （内容页应当 0 个；工具页允许，但会列出来供你判断）

退出码：0 = 无硬问题（越界/压槽/压叠），1 = 有硬问题。
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from layouts import SKILL_DIR, TOOL_SLOT_Y  # noqa: E402

_SCRIPTS = os.path.join(SKILL_DIR, "scripts", "courseware")
_DESIGN = os.path.join(_SCRIPTS, "design")
for _path in (_DESIGN, _SCRIPTS):
    if _path not in sys.path:
        sys.path.insert(0, _path)

CANVAS_W, CANVAS_H = 1280, 720


def check(spec):
    import components as C
    from rich_text import parse_rich
    from visual_plan_renderer import content_slots

    hard, growth = [], []
    for index, page in enumerate(spec.get("pages") or [], 1):
        plan = page.get("visualPlan") or {}
        elements = plan.get("elements") or []
        native = (page.get("subjectTool") or {}).get("type")
        slots = content_slots(page) if plan else {}
        texts = []
        for element in elements:
            box = element["box"]
            x, y, w, h = box["x"], box["y"], box["w"], box["h"]
            tag = element.get("source") or element.get("shape", "?")
            if x < 0 or y < 0 or x + w > CANVAS_W or y + h > CANVAS_H:
                hard.append("P%d %s 越界 (%d,%d) %d×%d" % (index, tag, x, y, w, h))
            if native and y + h > TOOL_SLOT_Y:
                hard.append("P%d %s 压工具安全槽（底边 %d > %d）"
                            % (index, tag, y + h, TOOL_SLOT_Y))
            if element.get("kind") != "text":
                continue
            texts.append((tag, x, y, w, h))
            style = element["style"]
            measured = C.measure_text_layout(
                parse_rich(slots.get(tag, "")) or [[]], w, h,
                style["fontSize"], style.get("lineSpacing", 1.35),
                style.get("padding", 0),
                line_height_factor=C.REAL_LINE_HEIGHT_FACTOR)
            if measured["height_deficit"] > 0:
                growth.append((index, tag, measured["height_deficit"], bool(native)))
        for left in range(len(texts)):
            for right in range(left + 1, len(texts)):
                _, x1, y1, w1, h1 = texts[left]
                _, x2, y2, w2, h2 = texts[right]
                overlap_x = max(0, min(x1 + w1, x2 + w2) - max(x1, x2))
                overlap_y = max(0, min(y1 + h1, y2 + h2) - max(y1, y2))
                if overlap_x > 4 and overlap_y > 4:
                    hard.append("P%d 文本压叠 %s ↔ %s（%d×%d）"
                                % (index, texts[left][0], texts[right][0],
                                   overlap_x, overlap_y))
    return hard, growth


def main():
    parser = argparse.ArgumentParser(description="pages.json 几何自检")
    parser.add_argument("--spec", required=True)
    args = parser.parse_args()
    with open(args.spec, encoding="utf-8") as handle:
        spec = json.load(handle)

    hard, growth = check(spec)
    print("《%s》  %d 页" % (spec.get("title", ""), len(spec.get("pages") or [])))
    print("-" * 62)
    content_growth = [item for item in growth if not item[3]]
    tool_growth = [item for item in growth if item[3]]

    print("① 越界 / 压安全槽 / 文本压叠：%d 项" % len(hard))
    for item in hard:
        print("   ✗ " + item)

    print("② 内容页会被渲染端撑高的文本框：%d 个%s"
          % (len(content_growth), "（应为 0）" if content_growth else " ✓"))
    for index, tag, deficit, _ in content_growth:
        print("   ✗ P%d %s 撑高 %.0fpx" % (index, tag, deficit))

    print("③ 工具页允许撑高（落进组件空白内边距）：%d 个" % len(tool_growth))
    for index, tag, deficit, _ in tool_growth:
        print("   · P%d %s 撑高 %.0fpx" % (index, tag, deficit))

    return 1 if hard or content_growth else 0


if __name__ == "__main__":
    sys.exit(main())
