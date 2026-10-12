#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版式库色板 —— 整册换配色只改这一个文件（或在简报里覆盖）。

默认是「深绿 · 米白」体系（粤教科技版小学科学四年级上册第 2 单元），
也是本库所有模板的默认色。任何一个模板都不写死色值，全部从这里取，
所以换色不会漏掉某个角落。
"""

DEFAULT_THEME = {
    # ── 主色阶 ──────────────────────────────────────────────
    "deep":    "#1E4D3B",   # 深绿：封面底、结论条底、标题字
    "mid":     "#2F6B4F",   # 中绿：引导语（lead）
    "accent":  "#4E8C6A",   # 亮绿：要点圆点 / 过程节点
    "light":   "#E3EDE7",   # 浅绿：卡片底、问题框底
    # ── 纸面与文字 ──────────────────────────────────────────
    "paper":   "#F7F5EF",   # 米白：内容页底色
    "ink":     "#26332E",   # 正文墨色（在米白底上对比度 12:1）
    # ── 强调与白 ────────────────────────────────────────────
    "gold":    "#C9A227",   # 金色：左侧锚点竖条、收尾圆点
    "white":   "#FFFFFF",
    # ── 深底上的次级文字 ────────────────────────────────────
    "meta":    "#C9D9CE",   # 封面学段信息
    "sub":     "#9FB8AB",   # 封面副题
    # ── 卡片内文字 ──────────────────────────────────────────
    "cardInk": "#1E4D3B",
}

# 换一套配色时的成组建议（在简报里覆盖其中之一即可成组生效）
# 每套预设都实测过 7 个文字位与底色的对比度，全部 ≥ 4.5:1（技能建议线）。
PRESETS = {
    # 深青 · 米白（信息科技 / 数学）
    "teal": {
        "deep": "#0F4C5C", "mid": "#1E6F7D", "accent": "#3E9BA8",
        "light": "#DCEAEE", "paper": "#F6F3EC", "ink": "#22302F",
        "gold": "#D9A441", "white": "#FFFFFF",
        "meta": "#C6DDE3", "sub": "#B7CFD5", "cardInk": "#0F4C5C",
    },
    # 赭石 · 米白（人文 / 语文）
    "ochre": {
        "deep": "#6B3A22", "mid": "#8C5233", "accent": "#B87A4B",
        "light": "#F0E4D6", "paper": "#F8F4EC", "ink": "#2E241C",
        "gold": "#C9A227", "white": "#FFFFFF",
        "meta": "#E0CBB8", "sub": "#D6BFA6", "cardInk": "#6B3A22",
    },
}


def make_theme(override=None):
    """叠加覆盖色，返回完整色板；遇到拼错的色名直接报错而不是静默忽略。"""
    theme = dict(DEFAULT_THEME)
    if not override:
        return theme
    if isinstance(override, str):          # 允许直接写预设名
        name = override.strip().lower()
        if name not in PRESETS:
            raise SystemExit("未知配色预设 %r；可选：%s"
                             % (override, "、".join(sorted(PRESETS))))
        theme.update(PRESETS[name])
        return theme
    if not isinstance(override, dict):
        raise SystemExit("theme 必须是对象（色名→色值）或预设名字符串")
    if override.get("preset"):
        theme.update(PRESETS.get(str(override["preset"]).lower(), {}))
    unknown = sorted(set(override) - set(DEFAULT_THEME) - {"preset"})
    if unknown:
        raise SystemExit("theme 里出现未知色名：%s；可选色名：%s"
                         % ("、".join(unknown), "、".join(sorted(DEFAULT_THEME))))
    for key, value in override.items():
        if key == "preset":
            continue
        if not (isinstance(value, str) and len(value) == 7 and value.startswith("#")):
            raise SystemExit("theme.%s 必须是 #RRGGBB（收到 %r）" % (key, value))
        theme[key] = value.upper()
    return theme


if __name__ == "__main__":
    import json
    print(json.dumps(DEFAULT_THEME, ensure_ascii=False, indent=2))
