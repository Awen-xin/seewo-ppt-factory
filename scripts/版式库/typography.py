#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版式库字体方案 —— 换字体/调字号只改这一个文件（或在简报里覆盖）。

与 theme.py（配色）平行：一个管颜色，一个管字。

为什么单独一个文件
------------------
字体名字写进 enbx 的是**系统字体名**（希沃白板字体下拉框里显示的那串），
所以换字体前必须先把 ttf 装进系统（见 install_fonts.py）。
本文件只记"名字 + 层级关系"，不存字体文件。

字重怎么表达
------------
中文字体的粗细靠**选不同字重的文件**（旗黑 80S / 60S / 50S），
不是靠 bold 标记 —— 对已经是粗字重的字体再叠 bold，客户端会做**伪粗**，
笔画糊在一起，投影到教室反而更看不清。
所以每个角色有两档：
    fonts      = 常规
    fonts_bold = 需要强调时（style 里 bold=True）换用的粗一档字重
两者都指定时，_t() 会把 bold 标记吃掉，只留下字重差异。

scale 是干什么的
----------------
用户反馈"后排同学看不清"，本质是字号偏小。scale 是**全库统一的字号倍数**，
作用在 size 与 min 上（下限也一起放大，否则 flow() 装不下时会自动降回原字号，
放大等于白做）。1.0 = 原始尺寸。
"""

# 渲染器默认字体（page_renderer.py 里的兜底值），也是 scale=1.0 时的样子
FALLBACK_FONT = "Microsoft YaHei"

# ── 默认方案：不动字体，不动字号 ────────────────────────────────────
DEFAULT_TYPO = {
    "scale": 1.0,
    "fonts": {},          # 空 = 交给渲染器默认（微软雅黑）
    "fonts_bold": {},
}

# ── 预设方案 ────────────────────────────────────────────────────────
#
# 字重是**实测选出来的**，不是照抄技能推荐。用 measure_font_gain.py 对同一段
# 课文在 24px 下量墨迹占比（墨迹越多 = 投影上越实、后排越看得清）：
#
#   微软雅黑 33.1%  ← 现状基准        微软雅黑Bold 51.4%（1.55×）
#   旗黑 80S 42.1%（1.27×）✔          旗黑 60S 31.8%（0.96×）
#   旗黑 50S 26.2%（0.79×）           润圆-75W 35.1%（1.06×）
#   润圆-65W 31.3%（0.94×）           润圆-55W 26.9%（0.81×）
#   润圆-45W 23.2%（0.70×）
#
# 结论（与直觉相反，务必记住）：
#   1. 汉仪这批字体里**只有旗黑 80S 明显粗过雅黑**（+12.7%），
#      润圆整族都比雅黑细 —— 润圆做正文是**退步**，45W 尤其细（-16%）。
#   2. 所以圆体只能用**最粗的 75W**，且只放在短文本（结论/提问），
#      长正文交给旗黑，靠黑体骨架保证清晰度。
#   3. 想要"更大"不能靠换字体，只能靠放大 fontSize —— 而放大需要精简文案，
#      见本文件末尾 PROVEN_SCALE 的说明。
_HANYI_FONTS = {
    "title":    "汉仪旗黑 80S",   # 1.27× —— 标题显著变粗，远看不散
    "lead":     "汉仪旗黑 60S",   # 0.96× —— 与正文同骨架，靠字号拉开层次
    "body":     "汉仪旗黑 60S",   # 0.96× —— 长正文要清晰，黑体优于圆体
    "item":     "汉仪旗黑 60S",
    "summary":  "汉仪润圆-75W",   # 1.06× —— 结论条用圆体收尾，柔和且略粗
    "question": "汉仪润圆-75W",   # 1.06× —— 提问要跳出来，圆体不刺眼
}
# ⚠ 注意：question 与 summary 在模板里是**恒定 bold=True**（深底白字的强调条），
# title 在 conclusion/_tool_header 里也是 bold=True。也就是说这两个角色
# 实际走的永远是 fonts_bold 这条路径 —— 圆体必须写在 fonts_bold 里才会出现，
# 写在 fonts 里会被静默跳过（第 7 课实测：润圆一个都没落上）。
_HANYI_BOLD = {
    # 字重本身已表达粗细，不再叠 bold，避免客户端伪粗把笔画糊在一起。
    "title":    "汉仪旗黑 80S",   # 已是最粗
    "lead":     "汉仪旗黑 80S",
    "body":     "汉仪旗黑 80S",
    "item":     "汉仪旗黑 80S",   # items 的"最后一条"加重，形成收束
    "summary":  "汉仪润圆-75W",   # 结论条：圆体收尾，柔和且略粗于雅黑
    "question": "汉仪润圆-75W",   # 提问框：圆体不刺眼，和黑体正文拉开气质
}

# 实测：内容不变时，全局字号倍率的**可用上限只有 1.02~1.03**。
# P3(evidence) 与 P7(bullets) 是硬瓶颈 —— 文案量已经把版面吃满，
# 再放大 3% 就会触发 flow() 的"下限字号也排不下"。
# 想要 22px → 26px（×1.18）必须先精简这两页的文案，不能靠调参数蒙过去。
PROVEN_SCALE = 1.02

PRESETS = {
    # 小学科学 · 课堂投影：默认**不动字号**（1.0），只换字体。
    # 字号倍率想要更高请先精简文案，否则 make_deck 会直接报错而不是静默缩字。
    "hanyi-science": {
        "scale": 1.0,
        "fonts": dict(_HANYI_FONTS),
        "fonts_bold": dict(_HANYI_BOLD),
    },
    # 只换字体 + 微调字号到实测上限
    "hanyi-max-size": {
        "scale": PROVEN_SCALE,
        "fonts": dict(_HANYI_FONTS),
        "fonts_bold": dict(_HANYI_BOLD),
    },
    # 只放大字号，不换字体（字体没装 / 要避开商用授权时的退路）
    "larger-only": {
        "scale": PROVEN_SCALE,
        "fonts": {},
        "fonts_bold": {},
    },
    # 只换字体，字号不动（想保持原版面密度时用）
    "hanyi-keep-size": {
        "scale": 1.0,
        "fonts": dict(_HANYI_FONTS),
        "fonts_bold": dict(_HANYI_BOLD),
    },
}


def make_typo(override=None):
    """与 theme.make_theme 同风格：预设名 / 对象 / None。"""
    typo = {k: (dict(v) if isinstance(v, dict) else v)
            for k, v in DEFAULT_TYPO.items()}
    if not override:
        return typo
    if isinstance(override, str):
        name = override.strip().lower()
        if name not in PRESETS:
            raise SystemExit("未知字体预设 %r；可选：%s"
                             % (override, "、".join(sorted(PRESETS))))
        return _merge(typo, PRESETS[name])
    if not isinstance(override, dict):
        raise SystemExit("typography 必须是对象或预设名字符串")
    if override.get("preset"):
        preset = str(override["preset"]).lower()
        if preset not in PRESETS:
            raise SystemExit("未知字体预设 %r；可选：%s"
                             % (override["preset"], "、".join(sorted(PRESETS))))
        _merge(typo, PRESETS[preset])
    if "scale" in override:
        scale = float(override["scale"])
        if not 0.8 <= scale <= 1.5:
            raise SystemExit("typography.scale 应在 0.8~1.5 之间（收到 %r）" % scale)
        typo["scale"] = scale
    for key in ("fonts", "fonts_bold"):
        if key in override:
            if not isinstance(override[key], dict):
                raise SystemExit("typography.%s 必须是对象（role → 字体名）" % key)
            merged = dict(typo[key]); merged.update(override[key])
            typo[key] = merged
    return typo


def _merge(base, extra):
    for key, value in extra.items():
        base[key] = dict(value) if isinstance(value, dict) else value
    return base


if __name__ == "__main__":
    import json
    print(json.dumps(PRESETS["hanyi-science"], ensure_ascii=False, indent=2))
