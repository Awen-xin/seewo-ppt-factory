#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把汉仪字体装进系统（复制 ttf 到 C:\\Windows\\Fonts + 写 HKLM 字体注册表）。

需要管理员权限。字体名用 fontTools 从 ttf 里读的**中文 Family/Full 名**，
与希沃白板字体下拉框里显示的名字一致。
"""
import os
import shutil
import sys
import winreg

sys.stdout.reconfigure(encoding="utf-8")

SRC = r"D:\_hanyi_fonts"
DEST = r"C:\Windows\Fonts"
REG_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"

# 文件名 → 期望显示名（fontTools 读出来的 nameID=4 中文全名）
FONTS = {
    "HYQiHei_80S.ttf":   "汉仪旗黑 80S",
    "HYQiHei_60S.ttf":   "汉仪旗黑 60S",
    "HYQiHei_50S.ttf":   "汉仪旗黑 50S",
    "HYRunYuan-75W.ttf": "汉仪润圆-75W",
    "HYRunYuan-65W.ttf": "汉仪润圆-65W",
    "HYRunYuan-55W.ttf": "汉仪润圆-55W",
    "HYRunYuan-45W.ttf": "汉仪润圆-45W",
    "HYRunYuan-35W.ttf": "汉仪润圆-35W",
}


def main():
    if not os.path.isdir(SRC):
        raise SystemExit("源目录不存在：%s" % SRC)
    os.makedirs(DEST, exist_ok=True)

    # 1) 复制
    copied = []
    for fn in FONTS:
        src = os.path.join(SRC, fn)
        if not os.path.isfile(src):
            print("  [skip] 源文件缺失 %s" % fn)
            continue
        dst = os.path.join(DEST, fn)
        if os.path.isfile(dst) and os.path.getsize(dst) == os.path.getsize(src):
            print("  [已存在] %s" % fn)
            copied.append(fn)
            continue
        shutil.copy2(src, dst)
        print("  [复制] %s -> %s" % (fn, dst))
        copied.append(fn)

    # 2) 注册表（HKLM 需要管理员）
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REG_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            for fn in copied:
                winreg.SetValueEx(key, "%s (TrueType)" % FONTS[fn], 0,
                                  winreg.REG_SZ, fn)
                print("  [注册] %s (TrueType) = %s" % (FONTS[fn], fn))
    except PermissionError:
        raise SystemExit("✗ 写注册表失败：没有管理员权限。\n"
                         "  请用「以管理员身份运行」的 PowerShell 重新执行本脚本。")
    except OSError as exc:
        raise SystemExit("✗ 写注册表失败：%s" % exc)

    print("\n✓ 安装完成 %d 款。重启希沃白板客户端后即可在字体列表里看到。"
          % len(copied))


if __name__ == "__main__":
    main()
