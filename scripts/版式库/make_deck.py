#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版式库生成器：把「课件简报」编译成 seewo 技能可直接消费的 pages.json。

一句话出课件，稳定版：

    1) 写一份简报 JSON（只写内容与想用的版式，不写任何坐标）
    2) python make_deck.py --brief briefs/xxx.json --out ../某课/pages.json
    3) 用技能链路落稿：run_build_v2.py --spec pages.json  →  enbx_video.py --sync

生成器在写文件前会**内联调用技能自己的校验器**（validate_deck），
所以"生成了但过不了校验"这种情况不会流到落稿阶段。

简报结构（示例见 briefs/第6课-植物的繁殖.json）：

{
  "spec": {
      "title": "第6课 植物的繁殖",
      "subject": "科学", "grade": "四年级", "topic": "植物的繁殖",
      "pagePlan": {"range": [5, 10]},
      "teachingObjectives": ["…", "…"],
      "creativeDirection": {"concept": "…", "visualMetaphor": "…",
                            "backgroundStrategy": "…"}
  },
  "theme": "teal",                     // 可选：预设名 或 {"deep": "#…"}
  "pages": [
      {"layout": "cover",   "title": "…", "lead": "…", "body": "…"},
      {"layout": "bullets", "title": "…", "lead": "…", "body": "…",
       "items": ["…", "…", "…"]},
      …
  ]
}
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import layouts                                                     # noqa: E402
from layouts import LayoutError, TEMPLATES, build_page, SKILL_DIR  # noqa: E402
from theme import make_theme                                      # noqa: E402
from typography import make_typo                                  # noqa: E402


def _load_validator():
    """加载技能自带的校验器；拿不到时返回 None（降级为只做结构检查）。"""
    scripts = os.path.join(SKILL_DIR, "scripts", "courseware")
    design = os.path.join(scripts, "design")
    for path in (design, scripts):
        if path not in sys.path:
            sys.path.insert(0, path)
    try:
        import validate_deck as module
    except Exception as exc:                                   # pragma: no cover
        print("⚠ 无法加载技能校验器（%s），跳过校验。" % exc)
        return None
    return module.validate_deck


def build_spec(brief):
    theme = make_theme(brief.get("theme"))
    typo = make_typo(brief.get("typography"))
    layouts.set_typography(typo)            # 字号倍率 + 字体族，对所有模板生效
    meta = brief.get("spec") or {}
    if not meta.get("title"):
        raise SystemExit("简报缺少 spec.title")

    pages, notices = [], []
    for index, page in enumerate(brief.get("pages") or [], 1):
        try:
            built, dropped = build_page(page, theme)
        except LayoutError as exc:
            raise SystemExit("第 %d 页（%s）排版失败：%s"
                             % (index, page.get("layout"), exc))
        built.pop("template", None)
        pages.append(built)
        if dropped:
            notices.append("第 %d 页 %s：简报里这些字段没被该版式使用，已忽略 → %s"
                           % (index, page.get("layout"), "、".join(dropped)))

    # 只要有任何一页挂了配图，就必须声明 imageStrategy=provided，
    # 否则校验器判"none 下不得声明前景配图"直接报错。
    has_img = any(
        e.get("kind") == "image"
        for p in pages
        for e in (p.get("visualPlan") or {}).get("elements", [])
    )
    spec = {
        "title": str(meta["title"]).strip(),
        "subject": meta.get("subject", ""),
        "grade": meta.get("grade", ""),
        "topic": meta.get("topic", ""),
        "imageStrategy": meta.get("imageStrategy") or ("provided" if has_img else "none"),
        "pagePlan": meta.get("pagePlan") or {"range": [5, 10]},
        "teachingObjectives": meta.get("teachingObjectives") or [],
        "visualPlanning": {
            "backgroundImageMinRatio": 0,
            "creativeDirection": meta.get("creativeDirection") or {},
        },
        "pages": pages,
    }
    return spec, notices


def describe(spec):
    rows, contours = [], set()
    try:
        import visual_plan_renderer as vpr
        silhouette_tokens = vpr.silhouette_tokens
    except Exception:
        silhouette_tokens = None
    for index, page in enumerate(spec["pages"], 1):
        plan = page.get("visualPlan") or {}
        elements = plan.get("elements") or []
        kinds = {}
        for element in elements:
            kinds[element["kind"]] = kinds.get(element["kind"], 0) + 1
        shape_count = kinds.get("shape", 0)
        if plan and silhouette_tokens:
            contours.add(tuple(sorted(silhouette_tokens(page))))
        native = (page.get("subjectTool") or {}).get("type")
        activity = (page.get("activity") or {}).get("activityType")
        label = page["layout"]
        if native:
            label += "(%s)" % native
        if activity:
            label += "(%s)" % activity
        rows.append((index, page["title"], label, len(elements), shape_count,
                     bool(plan)))
    return rows, contours


def main():
    parser = argparse.ArgumentParser(description="版式库：简报 → pages.json")
    parser.add_argument("--brief", required=True, help="简报 JSON 路径")
    parser.add_argument("--out", required=True, help="输出的 pages.json 路径")
    parser.add_argument("--no-validate", action="store_true",
                        help="跳过技能校验（不推荐）")
    args = parser.parse_args()

    with open(args.brief, encoding="utf-8") as handle:
        brief = json.load(handle)

    spec, notices = build_spec(brief)
    rows, contours = describe(spec)

    print("《%s》  %d 页" % (spec["title"], len(spec["pages"])))
    print("-" * 74)
    for index, title, layout, count, shape_count, has_plan in rows:
        flag = "" if has_plan else "  (组件页，无 visualPlan)"
        warn = "  ⚠ 装饰 shape %d 个" % shape_count if shape_count >= 5 else ""
        print("  P%-2d %-13s %-10s 元素 %-2d%s%s"
              % (index, layout, "「%s」" % title[:9], count, flag, warn))
    print("-" * 74)
    print("版面轮廓种类：%d（≥6 页需 ≥4 种）" % len(contours))
    for notice in notices:
        print("  ⚠ " + notice)

    if not args.no_validate:
        validator = _load_validator()
        if validator:
            errors, warnings = validator(spec)
            if errors:
                print("\n✗ 技能校验失败（%d 项）：" % len(errors))
                for item in errors:
                    print("   - %s" % item)
                print("\n未写出 %s" % args.out)
                return 2
            print("\n✓ 技能校验通过（%d 条告警）" % len(warnings))
            for item in warnings:
                print("   · %s" % item)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(spec, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("\n✓ 已写出 %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
