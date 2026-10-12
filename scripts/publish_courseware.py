#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_courseware.py — 希沃课件「一键发布」，并把云端同名副本压到恒定 1 份。

═══ 为什么需要它（2026-10-10 实测结论）═══
希沃客户端把「用本地 .enbx 打开的课件」一律当成**新记录**，于是
`本地 enbx → 打开 → 同步` 每跑一次，云端就**多一份同名课件**。
而 MCP 的 61 个工具里**没有删除云课件**的接口（只有 delete_slide / delete_elements），
`<UpstreamId>` 也只是「派生自」语义（仍会新建），`open_cloud_courseware + 编辑 + 同步`
才能更新同一份（但动画只能走 enbx，用不上）。
⇒ 兜底方案：**发布前先把云端同名旧副本删除**（驱动客户端 GUI，删除进回收站可恢复），
   再上传新版本 ⇒ 云端恒为 1 份。

用法：
    python publish_courseware.py "第6课 植物的繁殖-含视频.enbx"            # 保留云端旧副本
    python publish_courseware.py "….enbx" --cleanup                        # 只**扫描**同名旧副本（不删、不传）
    python publish_courseware.py "….enbx" --cleanup --yes                  # 确认后删除同名旧副本再传（云端恒 1 份）
    python publish_courseware.py --verify "第6课 植物的繁殖-含视频"         # 只查云端份数
    python publish_courseware.py --clean "第6课 植物的繁殖-含视频"          # 只删该校课件（进回收站可恢复）
    python publish_courseware.py "….enbx" --cleanup --dry-run              # 同上，只打印将做什么

🔒 删除前置闸门（2026-10-12 新增，防止误删）：
    `--cleanup` **默认只扫描不删**；必须显式加 `--yes` 才真正删除并上传。
    另设**保护名单**（环境变量 `SEEWO_NEVER_DELETE`，逗号分隔；或同目录 `never_delete.txt`，每行一个），
    命中即拒绝删除。删除走客户端 GUI、进回收站可恢复。

依赖：希沃客户端已打开并登录（MCP 7916 在听）；同目录下的 _del_batch4.ps1（GUI 删除脚本）。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import seewo_config                                     # noqa: E402
seewo_config.ensure_official_paths("mcp")
for _v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_v, None)


def _mcp():
    from mcp_client import McpHttpSession, find_live_port
    port = find_live_port(timeout=5)
    if not port:
        raise SystemExit("希沃 MCP 不可达（7916）；请先打开并登录希沃白板客户端。")
    s = McpHttpSession("http://127.0.0.1:%d/mcp" % port, timeout=300)
    s.initialize()
    return s


def T(o):
    from mcp_client import McpHttpSession
    return McpHttpSession.text_of(o)


def shells(s):
    try:
        st, o = s.tools_call("en_find_shells", {"searchingMode": "All"})
        return json.loads(T(o).strip().splitlines()[-1]).get("shells") or []
    except Exception:
        return []


def cloud_list(s, name):
    st, o = s.tools_call("search_cloud_courseware", {"keyword": name, "maxResults": 50})
    try:
        items = json.loads(T(o)).get("items") or []
    except Exception:
        items = []
    return [x for x in items if x.get("name") == name]


def close_same_name(s, name):
    n = 0
    for x in shells(s):
        if x.get("coursewareName") == name:
            s.tools_call("close_current_courseware",
                         {"shellId": x.get("id"), "syncBeforeClose": False})
            n += 1
    return n


def gui_delete(names, dry_run=False):
    """驱动客户端 GUI 删除云端所有叫这些名字的课件（进回收站，可恢复）。

    ⚠️ 列表行名带 `[课件]` / `[课件组]` 前缀，必须靠 rowPrefix 拼出来；
    不带前缀的精确名 `FindItemByProperty` 是**找不到**的（实测静默 0 删除）。
    确认弹窗的正文是「30天内可在 … 找回」，「回收站」三个字是单独的超链接节点
    （不在 Text 控件里）⇒ 守卫词必须用 `30天内可在`。
    """
    if isinstance(names, str):
        names = [names]
    ps1 = os.path.join(HERE, "_del_batch4.ps1")
    if not os.path.exists(ps1):
        return None, "未找到 _del_batch4.ps1"
    cfg = {"exact": list(names), "contains": [], "rowPrefix": "[课件]",
           "dialogGuard": "30天内可在"}
    tf = os.path.join(os.environ.get("TEMP", "."), "del_targets.json")
    tr = os.path.join(os.environ.get("TEMP", "."), "del_trace.txt")
    open(tf, "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False))
    if os.path.exists(tr):
        os.remove(tr)
    if dry_run:
        print("   [dry-run] 将执行 GUI 删除：%s" % ", ".join(names))
        return 0, "dry-run"
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", ps1], timeout=1800)
    log = open(tr, encoding="utf-8-sig", errors="replace").read() if os.path.exists(tr) else ""
    dele = len(re.findall(r"DELETED", log))
    return dele, log


def protected_names():
    """删除保护名单：环境变量 SEEWO_NEVER_DELETE（逗号分隔）+ scripts/never_delete.txt（每行一个）。"""
    names = set()
    for n in os.environ.get("SEEWO_NEVER_DELETE", "").split(","):
        if n.strip():
            names.add(n.strip())
    f = os.path.join(HERE, "never_delete.txt")
    if os.path.isfile(f):
        for ln in open(f, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                names.add(ln)
    return names


def main():
    ap = argparse.ArgumentParser(description="发布希沃课件并保持云端仅 1 份同名副本")
    ap.add_argument("enbx", nargs="?", help="要发布的 .enbx")
    ap.add_argument("--name", help="云端课件名（默认取文件名，不含扩展名）")
    ap.add_argument("--cleanup", action="store_true",
                    help="发布前**扫描**云端同名旧副本（默认只扫描不删）")
    ap.add_argument("--yes", action="store_true",
                    help="确认执行删除（配合 --cleanup；不加则只扫描、不删也不上传）")
    ap.add_argument("--verify", help="只查云端份数（传课件名）")
    ap.add_argument("--clean", action="append", default=None, metavar="名",
                    help="只删云端课件（可重复传；进回收站可恢复），不发布")
    ap.add_argument("--dry-run", action="store_true", help="只打印步骤，不做任何实际动作")
    ap.add_argument("--timeout", type=int, default=40, help="等待 shell 的轮询次数（每次 2s）")
    a = ap.parse_args()

    s = _mcp()

    if a.clean:
        print("== 清理云端课件（进回收站，可恢复）==")
        for nm in a.clean:
            before = cloud_list(s, nm)
            print("《%s》现有 %d 份" % (nm, len(before)))
        close_all = [x for x in shells(s) if x.get("coursewareName") in a.clean]
        for x in close_all:
            s.tools_call("close_current_courseware",
                         {"shellId": x.get("id"), "syncBeforeClose": False})
        if close_all:
            print("已关闭 %d 个同名 shell" % len(close_all))
            time.sleep(3)
        dele, log = gui_delete(a.clean, dry_run=a.dry_run)
        print("删除数：%s" % dele)
        if log and dele == 0:
            for ln in (log or "").splitlines():
                if "not found" in ln or "FAIL" in ln or "ABORT" in ln:
                    print("   " + ln.strip())
        if not a.dry_run:
            for nm in a.clean:
                after = cloud_list(s, nm)
                print("《%s》剩 %d 份 %s" % (nm, len(after), "✅" if not after else "⚠️"))
        return

    if a.verify:
        items = cloud_list(s, a.verify)
        print("云端《%s》共 %d 份：" % (a.verify, len(items)))
        for x in items:
            print("   localId=%s updateTime=%s" % (x.get("localId"), x.get("updateTime")))
        return

    if not a.enbx:
        raise SystemExit("需要给一个 .enbx（或 --verify 课件名）")

    enbx = os.path.abspath(a.enbx)
    if not os.path.isfile(enbx):
        raise SystemExit("文件不存在：%s" % enbx)
    # 关键：客户端给本地 enbx 的课件名取的是**文件名**（Document.xml 的 <Name> 会被无视）
    name = a.name or os.path.splitext(os.path.basename(enbx))[0]

    print("课件名：%s" % name)
    before = cloud_list(s, name)
    print("云端现有同名副本：%d 份" % len(before))

    if a.cleanup:
        # ── 🔒 删除前置闸门：先扫描列清单；未加 --yes 一律不删、也不上传 ──
        print("\n== 1/5 扫描云端同名副本（只读）==")
        if before:
            for x in before:
                print("   · localId=%s  updateTime=%s" % (x.get("localId"), x.get("updateTime")))
        else:
            print("   （云端没有同名副本，无需清理）")
        prot = protected_names()
        if name in prot:
            raise SystemExit("🛡 保护名单命中：`%s` 在 SEEWO_NEVER_DELETE / never_delete.txt 中，拒绝删除。" % name)
        if not a.yes and not a.dry_run:
            print("""
╔══════════════════════════════════════════════════════════════════════╗
║ 🔒 删除前置闸门：以上为**待删候选**，本次【未删除任何内容、也未上传】。 ║
╚══════════════════════════════════════════════════════════════════════╝
   确认要把这 %d 份同名副本全部删除（进回收站，可恢复）后再上传新版本，请重新运行并加 --yes：

       python publish_courseware.py "%s" --cleanup --yes

   若只想删其中某几个、保留其余，请改用 --clean --name 逐个处理。""" % (len(before), os.path.basename(enbx)))
            return
        print("\n== 2/5 关闭同名 shell ==")
        print("   关闭 %d 个" % close_same_name(s, name))
        print("\n== 3/5 删除云端同名旧副本（GUI，进回收站可恢复）==")
        if a.dry_run:
            print("   [dry-run] 将删除《%s》的 %d 份同名副本" % (name, len(before)))
            print("\n[dry-run] 到此为止（不做打开与同步）")
            return
        dele, log = gui_delete(name, dry_run=False)
        print("   删除数：%s" % dele)
        left = cloud_list(s, name)
        print("   删后剩余：%d 份" % len(left))
    else:
        print("\n· 跳过清理（未传 --cleanup）")

    if a.dry_run:
        print("\n[dry-run] 到此为止（不做打开与同步）")
        return

    print("\n== 4/5 打开本地课件并等待就绪 ==")
    os.startfile(enbx)
    sh = None
    for i in range(a.timeout):
        time.sleep(2)
        for x in shells(s):
            if x.get("coursewareName") == name:
                sh = x.get("id")
                break
        if sh:
            break
    if not sh:
        raise SystemExit("等不到 shell「%s」；客户端可能弹了「部分元素无法解析」对话框。" % name)
    print("   shell = %s" % sh)

    last = None
    for i in range(30):
        time.sleep(2)
        st, o = s.tools_call("get_current_courseware_info", {"shellId": sh})
        try:
            n = int(json.loads(T(o)).get("slideCount") or 0)
        except Exception:
            n = 0
        if n and n == last:
            break
        last = n
    print("   页数 = %s" % last)

    print("\n== 5/5 云同步 ==")
    remote = None
    for attempt in range(1, 7):
        st, o = s.tools_call("sync_current_courseware",
                             {"shellId": sh, "waitUntilSynced": True, "waitSeconds": 180})
        t = T(o)
        print("   第 %d 次 -> %s" % (attempt, (t or "").replace("\n", " ")[:140]))
        m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", t or "")
        if m:
            remote = m.group(0)
            break
        time.sleep(4)

    print("\n== 结果 ==")
    print("   云端 ID：%s" % (remote or "(未确认)"))
    after = cloud_list(s, name)
    print("   云端《%s》现在 %d 份" % (name, len(after)))
    for x in after:
        print("      localId=%s updateTime=%s" % (x.get("localId"), x.get("updateTime")))
    if len(after) == 1:
        print("   ✅ 已压到 1 份")
    elif len(after) > 1:
        print("   ⚠️ 仍有多份；可再跑一次 --cleanup --yes（清理需在客户端「云课件」页且窗口可前置）")
    if remote:
        close_same_name(s, name)


if __name__ == "__main__":
    main()
