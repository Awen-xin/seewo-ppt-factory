# -*- coding: utf-8 -*-
"""seewo_config.py —— 希沃课件工厂 · 统一配置中心（自动探测 + 单点覆盖）

把原先散落在各脚本里的「希沃账号 / 官方 skill 路径 / 客户端启动器 / 解释器 /
工作目录」收敛到一处，并尽量**自动探测**，使这套工具可以分享给其他教师而
不必改代码。

优先级（高 → 低）：
    显式函数参数  >  环境变量  >  配置文件  >  自动探测

配置文件（可选，按序查找第一个存在的）：
    $SEEWO_CONFIG
    <本文件同目录>/seewo_config.json
    ~/.seewo/seewo_config.json

环境变量：
    SEEWO_HOME          现役工作目录（pipeline 里相对路径的基准）；默认 = 当前工作目录
    SEEWO_SKILL_DIR     官方 seewo skill 根目录
    SEEWO_ACCOUNT       希沃账号（云缓存目录名）
    SEEWO_EASINOTE_EXE  swenlauncher.exe 绝对路径
    SEEWO_PYTHON        带 pymupdf/Pillow/opencv/python-docx 的解释器

自检：
    python seewo_config.py          # 打印解析结果（探测到的真实值 + 来源）
"""
import glob
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE = {}


# ------------------------------------------------------- 代理自动剥离 ----
def strip_proxies():
    """清掉进程内代理变量。

    MCP 只连本机 127.0.0.1:7916；一旦有 http(s)_proxy，探测请求会被送去代理、
    导致「7916 假死 / find_live_port 返回 None」——这是最容易被误判成
    「客户端没开」的坑（见 references/07-踩坑总表）。
    导入本模块即自动执行；只影响当前进程，不碰系统设置。
    """
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
              "all_proxy", "ALL_PROXY"):
        os.environ.pop(k, None)
    # 本机地址走直连，避免某些客户端读 NO_PROXY 再兜回代理
    np = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    if "127.0.0.1" not in np:
        merged = ",".join([p for p in (np, "127.0.0.1,localhost") if p])
        os.environ["NO_PROXY"] = merged
        os.environ["no_proxy"] = merged


strip_proxies()



# ------------------------------------------------------------------ 基础 ----
def _load_config():
    """读取配置文件（带缓存）。找不到就返回空 dict。"""
    if "_config" in _CACHE:
        return _CACHE["_config"]
    cands = []
    env = os.environ.get("SEEWO_CONFIG")
    if env:
        cands.append(env)
    cands.append(os.path.join(_HERE, "seewo_config.json"))
    cands.append(os.path.join(os.path.expanduser("~"), ".seewo", "seewo_config.json"))
    cfg = {}
    for path in cands:
        try:
            if path and os.path.isfile(path):
                with open(path, encoding="utf-8") as fh:
                    cfg = json.load(fh) or {}
                cfg["_source"] = path
                break
        except Exception:
            continue
    _CACHE["_config"] = cfg
    return cfg


def _pick(env_key, cfg_key):
    """按 环境变量 > 配置文件 取一个原始字符串。"""
    val = os.environ.get(env_key)
    if val:
        return val
    val = _load_config().get(cfg_key)
    if val:
        return val
    return None


def _first_file(paths):
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None


# ------------------------------------------------------------- 工作目录 ----
def get_home():
    """现役工作目录：pipeline / brief 里相对路径的基准。默认当前工作目录。"""
    val = _pick("SEEWO_HOME", "home")
    if val:
        return os.path.abspath(os.path.expanduser(val))
    return os.getcwd()


# -------------------------------------------------- 官方 skill 目录探测 ----
def _detect_skill_dir():
    """扫 ~/.workbuddy 下所有 seewo-easinote-assistant-skill* 目录，挑一个真正含
    scripts/courseware/build_v2.py 的。"""
    home = os.path.expanduser("~")
    bases = [
        os.path.join(home, ".workbuddy", "skills"),
        os.path.join(home, ".workbuddy", "plugins", "cache"),
    ]
    hits = []
    for base in bases:
        if not os.path.isdir(base):
            continue
        patterns = [
            os.path.join(base, "seewo-easinote-assistant-skill*"),
            os.path.join(base, "*", "seewo-easinote-assistant-skill*"),
            os.path.join(base, "*", "*", "seewo-easinote-assistant-skill*"),
        ]
        for pat in patterns:
            for path in glob.glob(pat):
                if not os.path.isdir(path):
                    continue
                if os.path.isfile(os.path.join(path, "scripts", "courseware", "build_v2.py")):
                    hits.append(path)
    if hits:
        # 优先无 "__" 后缀者，其次路径短的
        hits = sorted(set(hits),
                      key=lambda p: ("__" in os.path.basename(p), len(p)))
        return hits[0]
    return None


def get_skill_dir():
    """官方 seewo skill 根目录。"""
    if "skill_dir" in _CACHE:
        return _CACHE["skill_dir"]
    val = _pick("SEEWO_SKILL_DIR", "skill_dir")
    if val and os.path.isdir(val):
        _CACHE["skill_dir"] = val
        return val
    _CACHE["skill_dir"] = _detect_skill_dir()
    return _CACHE["skill_dir"]


def get_skill_scripts():
    d = get_skill_dir()
    return os.path.join(d, "scripts") if d else None


def get_skill_courseware():
    d = get_skill_scripts()
    return os.path.join(d, "courseware") if d else None


def get_skill_design():
    d = get_skill_courseware()
    return os.path.join(d, "design") if d else None


def get_mcp_dir():
    d = get_skill_scripts()
    return os.path.join(d, "mcp") if d else None


def ensure_official_paths(*which):
    """把官方 skill 的相关目录插进 sys.path。默认插 courseware/design + mcp。

    which 可取 "design" / "courseware" / "mcp"，不传则三个都插。
    """
    wanted = set(which) or {"design", "courseware", "mcp"}
    mapping = {"design": get_skill_design(),
               "courseware": get_skill_courseware(),
               "mcp": get_mcp_dir()}
    out = []
    for key in ("design", "courseware", "mcp"):
        if key in wanted and mapping[key]:
            if mapping[key] not in sys.path:
                sys.path.insert(0, mapping[key])
            out.append(mapping[key])
    return out


# ------------------------------------------------------------- 账号 ----
def _detect_account():
    data = os.path.join(os.environ.get("APPDATA", ""), "Seewo", "EasiNote5", "Data")
    if not os.path.isdir(data):
        return None
    cands = [d for d in os.listdir(data)
             if os.path.isdir(os.path.join(data, d, "Courseware"))]
    if not cands:
        return None
    cands.sort(key=lambda d: os.path.getmtime(os.path.join(data, d)), reverse=True)
    return cands[0]


def get_account():
    """希沃账号（= 云缓存 Data 下的目录名）。"""
    val = _pick("SEEWO_ACCOUNT", "account")
    if val:
        return str(val)
    return _detect_account()


def get_courseware_db_dir():
    """云缓存里 Courseware 目录：%APPDATA%\\Seewo\\EasiNote5\\Data\\<账号>\\Courseware"""
    val = _pick("SEEWO_COURSEWARE_DB", "courseware_db")
    if val:
        return os.path.abspath(os.path.expanduser(val))
    acct = get_account()
    if not acct:
        return None
    return os.path.join(os.environ.get("APPDATA", ""),
                        "Seewo", "EasiNote5", "Data", acct, "Courseware")


# ----------------------------------------------------- 客户端启动器 ----
def _extract_exe(command):
    """从 'HKCR\\iseewo.enbx\\shell\\open\\command' 的值里取出可执行文件路径。"""
    command = command.strip()
    if command.startswith('"'):
        end = command.find('"', 1)
        if end > 0:
            return command[1:end]
    return command.split(" ")[0]


def _launcher_near(exe):
    d = os.path.dirname(exe)
    for _ in range(5):
        cand = os.path.join(d, "Swenlauncher", "swenlauncher.exe")
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _from_registry():
    try:
        import winreg
    except Exception:
        return None
    probes = [(winreg.HKEY_CLASSES_ROOT, r"iseewo.enbx\shell\open\command"),
              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\iseewo.enbx\shell\open\command"),
              (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Classes\iseewo.enbx\shell\open\command")]
    for hive, sub in probes:
        try:
            with winreg.OpenKey(hive, sub) as key:
                value, _ = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        exe = _extract_exe(value)
        if exe and os.path.isfile(exe):
            found = _launcher_near(exe)
            if found:
                return found
    return None


def _detect_easinote_exe():
    roots = [r"D:\希沃白板", r"D:\Seewo", r"C:\Program Files\Seewo",
             r"C:\Program Files (x86)\Seewo", r"D:\Program Files\Seewo"]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for path in glob.glob(os.path.join(root, "**", "Swenlauncher", "swenlauncher.exe"),
                              recursive=True):
            return path
    return None


def get_easinote_exe():
    """swenlauncher.exe 绝对路径。"""
    val = _pick("SEEWO_EASINOTE_EXE", "easinote_exe")
    if val and os.path.isfile(val):
        return val
    return _from_registry() or _detect_easinote_exe()


# --------------------------------------------------------- 解释器 ----
def _detect_python():
    home = os.path.expanduser("~")
    cands = [
        os.path.join(home, ".workbuddy", "binaries", "python", "envs", "default",
                     "Scripts", "python.exe"),
        os.path.join(home, ".workbuddy", "binaries", "python", "envs", "default",
                     "bin", "python"),
    ]
    return _first_file(cands)


def get_python():
    """带 pymupdf/Pillow/opencv/python-docx 的解释器（取图、版式校验用）。"""
    val = _pick("SEEWO_PYTHON", "python")
    if val and os.path.isfile(val):
        return val
    return _detect_python() or sys.executable


# ------------------------------------------------------------- 自检 ----
def resolve_all():
    return {
        "home": (get_home(), "环境变量 SEEWO_HOME / 默认当前目录"),
        "skill_dir": (get_skill_dir(), "环境变量 SEEWO_SKILL_DIR / 自动扫描 ~/.workbuddy"),
        "account": (get_account(), "环境变量 SEEWO_ACCOUNT / 扫 %APPDATA%\\Seewo\\EasiNote5\\Data"),
        "courseware_db": (get_courseware_db_dir(), "由 account 推导"),
        "easinote_exe": (get_easinote_exe(), "注册表 / 扫常见安装路径"),
        "python": (get_python(), "环境变量 SEEWO_PYTHON / 托管 default 环境"),
    }


def main():
    print("═" * 68)
    print("希沃课件工厂 · 配置自检")
    print("═" * 68)
    src = _load_config().get("_source")
    print("配置文件：%s" % (src or "(无，全部走环境变量/自动探测)"))
    print("-" * 68)
    bad = []
    for key, (value, how) in resolve_all().items():
        mark = "OK " if value else "!! "
        if not value:
            bad.append(key)
        print("%s%-14s %s" % (mark, key, value or "(未探测到)"))
        print("     └ 来源：%s" % how)
    print("═" * 68)
    if bad:
        print("⚠ 以下项未探测到，请用环境变量或 seewo_config.json 指定：%s" % "、".join(bad))
        return 1
    print("✅ 全部就绪")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
