# -*- coding: utf-8 -*-
"""调用技能 build_v2.py 的包装器：补上本机真实的 swenlauncher 路径。

起因：build_v2.py 的 _find_swenlauncher() 先查注册表
（HKCR\\iseewo.enbx\\shell\\open\\command，用 reg.exe），
而本机安全策略拦掉了 reg.exe；它的三个硬编码候选路径是
D:\\Seewo\\... 与 C:\\Program Files[ (x86)]\\Seewo\\...，
本机希沃装在 D:\\希沃白板\\... 下，全都不匹配，于是直接抛
"找不到课件启动程序"。

这里只替换 _find_swenlauncher 的返回值，其余流程（校验、渲染、
导入、原生背景、元素叠加、同步门控）保持技能原样，不做任何降级。
"""
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seewo_config                                     # noqa: E402

SKILL = seewo_config.get_skill_dir()
if not SKILL:
    raise SystemExit("找不到官方 seewo skill 目录；请设置环境变量 SEEWO_SKILL_DIR。")
BUILD = os.path.join(SKILL, "scripts", "courseware", "build_v2.py")
LAUNCHER = seewo_config.get_easinote_exe()

if not LAUNCHER or not os.path.exists(LAUNCHER):
    raise SystemExit("找不到 swenlauncher.exe；请设置环境变量 SEEWO_EASINOTE_EXE。当前值：%s" % LAUNCHER)

_spec = importlib.util.spec_from_file_location("build_v2_mod", BUILD)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["build_v2_mod"] = _mod
_spec.loader.exec_module(_mod)

_mod._find_swenlauncher = lambda: LAUNCHER

sys.argv = ["build_v2.py"] + sys.argv[1:]
_mod.main()
