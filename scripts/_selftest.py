# -*- coding: utf-8 -*-
"""临时：Phase 2 导入/接口自检（跑完可删）。

分两类验证：
  A. 库型脚本 —— 直接 import，验证能加载（含官方 skill 依赖链）
  B. CLI 型脚本 —— 跑 --help，验证参数接口正常（模块级 argparse，不该被 import）
"""
import importlib
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(BASE, "scripts")
sys.path.insert(0, S)
sys.path.insert(0, os.path.join(S, "版式库"))

PY = sys.executable
LIB_MODS = ["seewo_config", "seewo_build", "enbx_video", "enbx_group", "enbx_anim",
            "enbx_dump", "seewo_mcp", "publish_courseware", "_verify_v2",
            "layouts", "make_deck", "check_geometry", "typography", "theme",
            "anim_presets", "install_fonts"]
CLI_SCRIPTS = ["enbx_shot.py", "_cloud_shot.py", "教材取图.py"]

print("── A. 库型脚本 import ──")
ok, bad = [], []
for m in LIB_MODS:
    try:
        importlib.import_module(m)
        ok.append(m)
    except SystemExit as exc:
        bad.append((m, "SystemExit(%s)" % exc.code))
    except Exception as exc:
        bad.append((m, "%s: %s" % (type(exc).__name__, str(exc)[:110])))
print("  OK  :", ", ".join(ok) or "(无)")
if bad:
    for m, e in bad:
        print("  FAIL: %-20s %s" % (m, e))

print("── B. CLI 型脚本 --help ──")
for name in CLI_SCRIPTS:
    path = os.path.join(S, name)
    r = subprocess.run([PY, path, "--help"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = (r.stdout or r.stderr or "").strip().splitlines()
    head = tail[0] if tail else "(无输出)"
    print("  %-6s %-16s %s" % ("OK" if r.returncode == 0 else "FAIL", name, head[:70]))

print("── C. 官方 skill 依赖链 ──")
import seewo_config
print("  skill_dir    =", seewo_config.get_skill_dir())
print("  easinote     =", seewo_config.get_easinote_exe())
print("  courseware_db=", seewo_config.get_courseware_db_dir())

sys.exit(1 if bad else 0)
