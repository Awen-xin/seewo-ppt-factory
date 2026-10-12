#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seewo_build.py —— 希沃课件「一条流水线」构建器。

把之前散落的几步串成一条可重复执行的链：

    源课件(.enbx/.enbx缓存目录)
      ① 插视频   enbx_video.build      （本地造含真实 <Video> 的 enbx）
      ② 分组     enbx_group.build      （图+图注、面板+文字 … 一次点击同时动）
      ③ 注动画   enbx_anim.build       （进入 / 退出 / 强调）
      ④ 发布     publish_courseware.py （清理云端同名旧副本 → 上传 → 云端恒 1 份）

为什么顺序是「视频先、分组次、动画最后」：
    enbx_video 会**整页重写**（clean_slide_xml 归一化外壳），分组产生的 <Group>
    嵌套结构经不起它重写；反过来，分组/动画只做就地 XML 编辑，不会碰视频。
    所以视频必须在最前。

用法：
    python seewo_build.py pipeline.json                 # 全流程（不含发布）
    python seewo_build.py pipeline.json --publish       # 全流程 + 发布上云
    python seewo_build.py pipeline.json --only group    # 只跑某一步
    python seewo_build.py pipeline.json --from anim     # 从某一步跑到尾
    python seewo_build.py pipeline.json --dry-run

pipeline.json：
    {
      "src":   "第6课-植物的繁殖/第6课 植物的繁殖.enbx",
      "out":   "第6课-植物的繁殖/第6课 植物的繁殖-含视频.enbx",
      "name":  "第6课 植物的繁殖-含视频",        // 云端课件名（默认取 out 文件名）
      "video": { "path": "…/u2-l06.mp4", "page": "last",
                 "title": "看一看：植物的繁殖", "sub": "…" },
      "group": "第6课-植物的繁殖/v2/group.json",  // 可省略
      "anim":  "第6课-植物的繁殖/v2/anim.json",   // 可省略
      "publish": { "cleanup": true }              // 缺省 false：不清理旧副本；true=显式授权删同名旧副本
    }

🔒 publish.cleanup 是「删除授权开关」：**缺省不删**（只上传、保留云端旧副本）；
   写 true 才在发布前删除云端同名旧副本（带 --yes 执行），使云端恒 1 份。
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import seewo_config                                     # noqa: E402

# 内容路径（pipeline / 视频 / 产物）以「现役工作目录」为基准；脚本兄弟模块仍按 HERE 找。
HOME = seewo_config.get_home()


def _r(p):
    """把相对路径解析成绝对路径：优先相对 SEEWO_HOME，回退脚本目录/当前目录。"""
    if not p or os.path.isabs(p):
        return p
    for base in (HOME, HERE, os.getcwd()):
        cand = os.path.join(base, p)
        if os.path.exists(cand):
            return cand
    return os.path.join(HOME, p)


STAGES = ["video", "group", "anim", "publish"]


def log(msg):
    print(msg, flush=True)


def stage_video(cfg, cur, dry):
    v = cfg.get("video") or {}
    if not v.get("path"):
        return cur
    import enbx_video
    out = cfg["_tmp_video"]
    name = cfg["name"]
    vpath = _r(v["path"])
    if not os.path.isfile(vpath):
        raise SystemExit("视频文件不存在：%s" % vpath)
    if dry:
        log("[dry-run] ① 插视频 %s → %s" % (vpath, out))
        return cur
    log("\n════ ① 插视频 ════")
    enbx_video.build(cur, vpath, out, name,
                     v.get("page", "last"), v.get("title"), v.get("sub"))
    return out


def stage_group(cfg, cur, dry):
    if not cfg.get("group"):
        return cur
    import enbx_group
    spec = json.load(open(_r(cfg["group"]), encoding="utf-8"))
    out = cfg["_tmp_group"]
    if dry:
        log("[dry-run] ② 分组 %s" % cfg["group"])
        return cur
    log("\n════ ② 分组（图+图注 / 面板+文字 一次点击同时动）════")
    enbx_group.build(cur, spec, out, dry_run=False)
    return out


def stage_anim(cfg, cur, dry):
    if not cfg.get("anim"):
        return cur
    import enbx_anim
    plan = json.load(open(_r(cfg["anim"]), encoding="utf-8"))
    out = cfg["out"]
    log("\n════ ③ 注动画（进入 / 退出 / 强调）════")
    n = enbx_anim.build(cur, plan, out, dry_run=dry)
    if dry:
        return cur
    if n == 0:
        raise SystemExit("没有注入任何动画，请检查 match/index")
    return out


def stage_publish(cfg, cur, dry):
    # ⚠️ 必须发 cfg["out"]：用 --only publish 时 cur 还是 src（干净源！），
    #    照 cur 发会把"无视频无动画"的源课件推上云。
    target = _r(cfg["out"])
    if not os.path.isfile(target):
        raise SystemExit("❌ 产物不存在，无法发布：%s" % target)
    cur = target
    pub = os.path.join(HERE, "publish_courseware.py")
    args = [sys.executable, pub, cur]
    pub_cfg = cfg.get("publish") or {}
    # 🔒 删除闸门：只有 pipeline 里显式写 "cleanup": true 才清理同名旧副本。
    #    写入配置 = 用户显式授权 ⇒ 带 --yes 直接执行；
    #    缺省/false = 未授权 ⇒ 保留云端旧副本（只上传，不删）。
    #    （无参数的交互式场景请直接用 publish_courseware.py --cleanup 先扫描、再按提示加 --yes）
    do_cleanup = bool(pub_cfg.get("cleanup", False))
    if do_cleanup:
        args += ["--cleanup", "--yes"]
        auth = "✅ 已授权（pipeline 配置 publish.cleanup=true）"
    else:
        auth = "⏸ 未授权清理（publish.cleanup 缺省/false）→ 保留云端旧副本"
    if dry:
        args.append("--dry-run")
    log("\n════ ④ 发布上云（先清同名旧副本，再上传）════")
    log("   清理授权：%s" % auth)
    log("   " + " ".join('"%s"' % a for a in args))
    subprocess.run(args)
    return cur


RUNNERS = {"video": stage_video, "group": stage_group,
           "anim": stage_anim, "publish": stage_publish}


def main():
    ap = argparse.ArgumentParser(description="希沃课件一条流水线构建器")
    ap.add_argument("config", help="pipeline.json")
    ap.add_argument("--publish", action="store_true", help="跑完后发布上云")
    ap.add_argument("--only", choices=STAGES, help="只跑某一步")
    ap.add_argument("--from", dest="frm", choices=STAGES, help="从某一步跑到尾")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cfg = json.load(open(_r(a.config), encoding="utf-8"))
    cfg.setdefault("name", os.path.splitext(os.path.basename(cfg["out"]))[0])
    # 中间产物放在产物自己的目录里（不要写死到某一课，否则会污染别的课）
    _outdir = os.path.dirname(_r(cfg["out"]))
    cfg["_tmp_video"] = os.path.join(_outdir, "_step1_video.enbx")
    cfg["_tmp_group"] = os.path.join(_outdir, "_step2_group.enbx")

    todo = [s for s in STAGES if (s != "publish" or a.publish)]
    if a.only:
        todo = [a.only]
    elif a.frm:
        todo = todo[STAGES.index(a.frm):]
        if "publish" not in todo and a.publish:
            todo.append("publish")

    src = _r(cfg["src"])
    out = _r(cfg["out"])
    if not os.path.isfile(src):
        raise SystemExit("源文件不存在：%s" % src)
    import shutil
    # 只有真要重建时才备份旧产物；--only publish 不该把上一份备份冲掉
    if (any(s in todo for s in ("video", "group", "anim"))
            and os.path.abspath(src) != os.path.abspath(out) and os.path.isfile(out)):
        bak = out + ".prebuild.bak"
        shutil.copy2(out, bak)
        log("已备份旧产物 → %s" % os.path.basename(bak))

    t0 = time.time()
    cur = src
    log("源：%s\n目标：%s\n阶段：%s" % (cfg["src"], cfg["out"], " → ".join(todo)))
    for s in todo:
        cur = RUNNERS[s](cfg, cur, a.dry_run) or cur
    # 收尾：清掉中间产物
    for k in ("_tmp_video", "_tmp_group"):
        p = cfg[k]
        if os.path.abspath(p) not in (os.path.abspath(src), os.path.abspath(out)) \
                and os.path.isfile(p):
            os.remove(p)
    log("\n完成，用时 %.0fs。产物：%s" % (time.time() - t0, cfg["out"]))


if __name__ == "__main__":
    main()
