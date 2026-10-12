# -*- coding: utf-8 -*-
"""_sync_check.py —— skill/scripts 与「现役目录」的一致性校验与快照。

模型（见 _规划/01-方案决策记录.md）：
    现役目录  …/02-课件/希沃白板/*.py   = 开发主场（你日常改脚本的地方）
    skill/scripts/*.py                  = 发布快照（分享给别人用，独立可跑）
    本工具负责比对两者，防止「改了主场忘了同步快照」。

用法：
    python _sync_check.py              # 只报告差异（退出码恒 0）
    python _sync_check.py --check      # 有差异 → 退出码 1（发布前把关）
    python _sync_check.py --snapshot   # 把现役脚本复制进 skill/scripts 并写 _SNAPSHOT.json
    python _sync_check.py --list       # 只列出清单

现役目录定位：环境变量 SEEWO_HOME → 否则取 skill 的上一级目录
（本文件在 <现役>/skill-希沃课件工厂/scripts/ 下，故上一级即现役目录）。
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)                       # …/skill-希沃课件工厂
LIVE = os.environ.get("SEEWO_HOME") or os.path.dirname(SKILL_ROOT)
SNAPSHOT_FILE = os.path.join(HERE, "_SNAPSHOT.json")

# (skill 内相对路径, [现役目录内相对路径…])  —— 允许一个脚本映射到多处（如 run_build_v2）
MANIFEST = [
    ("seewo_config.py",        ["seewo_config.py"]),
    ("seewo_build.py",         ["seewo_build.py"]),
    ("enbx_video.py",          ["enbx_video.py"]),
    ("enbx_group.py",          ["enbx_group.py"]),
    ("enbx_anim.py",           ["enbx_anim.py"]),
    ("enbx_dump.py",           ["enbx_dump.py"]),
    ("enbx_shot.py",           ["enbx_shot.py"]),
    ("publish_courseware.py",  ["publish_courseware.py"]),
    ("_verify_v2.py",          ["_verify_v2.py"]),
    ("_cloud_shot.py",         ["_cloud_shot.py"]),
    ("seewo_mcp.py",           ["seewo_mcp.py"]),
    ("教材取图.py",             ["教材取图.py"]),
    ("_del_batch4.ps1",        ["_del_batch4.ps1"]),
    ("run_build_v2.py",        ["第6课-植物的繁殖/run_build_v2.py",
                                "第7课-种子的传播/run_build_v2.py"]),
    ("版式库/anim_presets.py",   ["版式库/anim_presets.py"]),
    ("版式库/check_geometry.py", ["版式库/check_geometry.py"]),
    ("版式库/install_fonts.py",  ["版式库/install_fonts.py"]),
    ("版式库/layouts.py",        ["版式库/layouts.py"]),
    ("版式库/make_deck.py",      ["版式库/make_deck.py"]),
    ("版式库/theme.py",          ["版式库/theme.py"]),
    ("版式库/typography.py",     ["版式库/typography.py"]),
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_map():
    """{skill相对路径: sha256}，用于写入快照。"""
    out = {}
    for skill_rel, _ in MANIFEST:
        p = os.path.join(HERE, skill_rel)
        if os.path.isfile(p):
            out[skill_rel] = sha256(p)
    return out


def official_skill_tag():
    """记录配对官方 skill 的关键指纹（目录名 + build_v2.py 哈希前 12 位）。"""
    try:
        sys.path.insert(0, HERE)
        import seewo_config
        d = seewo_config.get_skill_dir()
        if not d:
            return None
        build = os.path.join(d, "scripts", "courseware", "build_v2.py")
        tag = os.path.basename(d)
        if os.path.isfile(build):
            tag += "@" + sha256(build)[:12]
        return tag
    except Exception:
        return None


def compare():
    """逐条比对，返回 (rows, drift_count)。row = (状态, skill_rel, live_rel, 备注)。"""
    rows = []
    drift = 0
    for skill_rel, live_rels in MANIFEST:
        sp = os.path.join(HERE, skill_rel)
        s_ok = os.path.isfile(sp)
        s_hash = sha256(sp) if s_ok else None
        for live_rel in live_rels:
            lp = os.path.join(LIVE, live_rel)
            l_ok = os.path.isfile(lp)
            if not s_ok and not l_ok:
                rows.append(("缺失", skill_rel, live_rel, "两边都没有"))
                drift += 1
            elif s_ok and not l_ok:
                rows.append(("仅快照", skill_rel, live_rel, "现役目录缺此文件"))
                drift += 1
            elif not s_ok and l_ok:
                rows.append(("仅现役", skill_rel, live_rel, "skill 快照缺此文件"))
                drift += 1
            else:
                l_hash = sha256(lp)
                if l_hash == s_hash:
                    rows.append(("一致", skill_rel, live_rel, ""))
                else:
                    st, lt = os.path.getmtime(sp), os.path.getmtime(lp)
                    newer = "现役更新" if lt > st else "快照更新"
                    rows.append(("漂移", skill_rel, live_rel, newer))
                    drift += 1
    return rows, drift


def cmd_report(as_check):
    rows, drift = compare()
    print("现役目录：%s" % LIVE)
    print("快照目录：%s" % HERE)
    print("-" * 72)
    groups = {"一致": [], "漂移": [], "仅快照": [], "仅现役": [], "缺失": []}
    for status, s_rel, l_rel, note in rows:
        groups[status].append((s_rel, l_rel, note))
    for status in ("漂移", "仅快照", "仅现役", "缺失"):
        for s_rel, l_rel, note in groups[status]:
            extra = ("  [%s]" % note) if note else ""
            print("  %-6s %-24s ← %s%s" % (status, s_rel, l_rel, extra))
    print("-" * 72)
    print("一致 %d / 共 %d 条映射" % (len(groups["一致"]), len(rows)))
    # 顺带校验快照清单是否齐
    if os.path.isfile(SNAPSHOT_FILE):
        try:
            snap = json.load(open(SNAPSHOT_FILE, encoding="utf-8"))
            stale = [k for k, v in (snap.get("files") or {}).items()
                     if digest_map().get(k) != v]
            if stale:
                print("⚠ _SNAPSHOT.json 与当前脚本不一致（%d 个）：%s"
                      % (len(stale), "、".join(stale)))
                drift += len(stale)
            else:
                print("✓ _SNAPSHOT.json 与当前快照一致（快照日期 %s）"
                      % snap.get("snapshot_date"))
        except Exception as exc:
            print("⚠ 无法读取 _SNAPSHOT.json：%s" % exc)
    else:
        print("· 尚无 _SNAPSHOT.json（跑 --snapshot 生成）")
    if drift:
        print("\n发现 %d 处差异。要发布快照请跑：python _sync_check.py --snapshot" % drift)
    else:
        print("\n✅ 完全一致，无漂移")
    if as_check and drift:
        return 1
    return 0


def cmd_snapshot():
    rows, _ = compare()
    copied, missing = [], []
    for skill_rel, live_rels in MANIFEST:
        src = os.path.join(LIVE, live_rels[0])
        dst = os.path.join(HERE, skill_rel)
        if not os.path.isfile(src):
            missing.append(skill_rel)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(skill_rel)
    snap = {
        "snapshot_date": datetime.date.today().isoformat(),
        "paired_official_skill": official_skill_tag(),
        "live_dir": LIVE,
        "files": digest_map(),
    }
    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as fh:
        json.dump(snap, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print("已快照 %d 个文件 → %s" % (len(copied), HERE))
    print("配对官方 skill：%s" % snap["paired_official_skill"])
    print("清单写入：%s" % SNAPSHOT_FILE)
    if missing:
        print("⚠ 现役目录缺失（未快照）：%s" % "、".join(missing))
    return 0


def cmd_list():
    print("skill 快照相对路径           ← 现役目录路径")
    print("-" * 72)
    for skill_rel, live_rels in MANIFEST:
        print("  %-26s ← %s" % (skill_rel, " | ".join(live_rels)))
    print("-" * 72)
    print("共 %d 条映射" % len(MANIFEST))
    return 0


# ------------------------------------------------------------ install ----
# 安装 = 把 skill 载荷发到用户级 skills 目录，供 WorkBuddy 自动识别。
# 只发「发布物」：SKILL.md / references / scripts / assets；**不含** _规划（内部规划件）。
DEFAULT_INSTALL_DIR = os.path.join(
    os.path.expanduser("~"), ".workbuddy", "skills", "seewo-courseware-factory")
PAYLOAD = ["SKILL.md", "README.md", "VERSION", "CHANGELOG.md",
           "自检.bat", "references", "scripts", "assets"]
_EXCLUDE_DIRS = {"__pycache__"}
_EXCLUDE_SUFFIX = (".pyc",)
# 构建产物不进分发物：只对作者本机有意义，且含本机绝对路径
_EXCLUDE_REL = {"scripts/_SNAPSHOT.json", "scripts/_INSTALL.json"}


def _iter_payload():
    """产出 (skill 内相对路径, 绝对源路径)。"""
    for item in PAYLOAD:
        src = os.path.join(SKILL_ROOT, item)
        if os.path.isfile(src):
            yield item, src
        elif os.path.isdir(src):
            for dp, dns, fns in os.walk(src):
                dns[:] = [d for d in dns if d not in _EXCLUDE_DIRS]
                for fn in fns:
                    if fn.endswith(_EXCLUDE_SUFFIX):
                        continue
                    ap = os.path.join(dp, fn)
                    rel = os.path.relpath(ap, SKILL_ROOT).replace("\\", "/")
                    if rel in _EXCLUDE_REL:
                        continue
                    yield rel, ap


def _skill_name():
    """从 SKILL.md front-matter 读 name。"""
    try:
        for line in open(os.path.join(SKILL_ROOT, "SKILL.md"), encoding="utf-8"):
            if line.lower().startswith("name:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return os.path.basename(SKILL_ROOT)


def skill_version():
    """读技能根 VERSION —— 写进 _INSTALL.json，供教师比对"我是不是旧版"。"""
    try:
        with open(os.path.join(SKILL_ROOT, "VERSION"), encoding="utf-8") as fh:
            v = fh.read().strip()
        return v or "unknown"
    except OSError:
        return "unknown"


def cmd_install(dest, force=False):
    dest = os.path.abspath(dest)
    payload = list(_iter_payload())
    if not payload:
        print("✗ 无可安装内容（PAYLOAD 为空）")
        return 2
    existed = os.path.isdir(dest)
    if existed and not force:
        print("· 目标已存在，将幂等覆盖（不改动目标里 PAYLOAD 之外的文件）")
    copied, files_map = [], {}
    for rel, src in payload:
        dst = os.path.join(dest, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        files_map[rel] = sha256(src)
        copied.append(rel)
    rec = {
        "skill_name": _skill_name(),
        "skill_version": skill_version(),
        "installed_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_skill_root": SKILL_ROOT,
        "paired_official_skill": official_skill_tag(),
        "file_count": len(copied),
        "files": files_map,
    }
    with open(os.path.join(dest, "_INSTALL.json"), "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print("%s已安装 %d 个文件 → %s" % ("✅ " if not existed else "♻️ 已刷新 ", len(copied), dest))
    print("  skill 名称：%s（版本 v%s）" % (rec["skill_name"], rec["skill_version"]))
    print("  配对官方 skill：%s" % rec["paired_official_skill"])
    print("  安装记录：%s" % os.path.join(dest, "_INSTALL.json"))
    print("  安装后自检：python %s" % os.path.join(dest, "scripts", "_selftest.py"))
    return 0


def main():
    ap = argparse.ArgumentParser(description="skill 快照 <-> 现役目录 一致性校验 / 安装")
    ap.add_argument("--check", action="store_true", help="有差异时返回非零码")
    ap.add_argument("--snapshot", action="store_true", help="现役 → 快照")
    ap.add_argument("--list", action="store_true", help="只列清单")
    ap.add_argument("--install", action="store_true",
                    help="安装到用户级 skills（默认 ~/.workbuddy/skills/seewo-courseware-factory）")
    ap.add_argument("--install-dir", default=None, help="自定义安装目录（配合 --install）")
    ap.add_argument("--force", action="store_true", help="安装时不做存在性提示")
    a = ap.parse_args()
    if a.install:
        return cmd_install(a.install_dir or DEFAULT_INSTALL_DIR, a.force)
    if a.snapshot:
        return cmd_snapshot()
    if a.list:
        return cmd_list()
    return cmd_report(a.check)


if __name__ == "__main__":
    raise SystemExit(main())
