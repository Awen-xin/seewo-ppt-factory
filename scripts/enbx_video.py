#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""enbx_video.py —— 给希沃白板课件「自动化插入本地视频」，并同步上云。

背景（为什么必须这么做）：
    希沃白板 MCP 的 61 个工具里 **没有任何 add_video_element**；
    SlideML（RenderSlideML）只认 Page/TextElement/Image，`<Video>` 会被
    当作「未知标签」忽略；set_element_properties 也没有 media/video 属性组；
    PPTX 导入（add_movie）会被拍平成空页。
    ⇒ 唯一可行的路：**自己造一个含真实 `<Video>` 元素的本地 .enbx →
       用 os.startfile 让客户端以「本地课件」打开 → sync_current_courseware 推上云**。
       本地课件不会被云端回灌覆盖（云课件一打开就会重新下载、覆盖注入内容）。

用法：
    python enbx_video.py --src <缓存目录|.enbx> --video <x.mp4> [选项]

参数：
    --src    源课件：希沃缓存目录（...\\Courseware\\<localId>）或一个 .enbx
    --video  要插入的本地视频（mp4）
    --page   视频页放第几页；默认 last（追加到末尾）。给 N 则替换第 N 页
    --name   云端课件名（不含扩展名）。默认取 --out 的文件名
    --out    输出的 .enbx 路径。默认在 --src 同级生成 <name>.enbx
    --title  视频页大标题
    --sub    视频页副标题
    --sync   打开后自动触发云同步并等待
    --no-open  只生成 enbx，不打开（调试用）

示例：
    python enbx_video.py \
        --src "<%APPDATA%>\\Seewo\\EasiNote5\\Data\\<账号>\\Courseware\\<localId>" \
        --video "D:\\...\\u2-l05.mp4" --name "第5课-番茄的一生-含视频" --sync

注意：
    * 调用前必须清代理：unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
    * 打开 .enbx 必须用 os.startfile（ensys_open_file 会把它当可执行文件，报错）
    * 同名云课件会撞车：open_cloud_courseware 按名称模糊匹配、选「最近更新的」，
      所以废稿务必删掉，否则可能打开到错的那份。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seewo_config                                    # noqa: E402
seewo_config.ensure_official_paths("design", "courseware", "mcp")
from enbx_backend import _text_xml, _nid          # noqa: E402
import enbx_templates as T                        # noqa: E402
from mcp_client import McpHttpSession, find_live_port  # noqa: E402

for _v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_v, None)

BOM = b"\xef\xbb\xbf"


# ---------------------------------------------------------------- enbx I/O ----
COURSEWARE_DB_DIR = seewo_config.get_courseware_db_dir()


def resolve_current(s):
    """--src current：把「当前打开的课件」解析成本地缓存目录。

    云课件拿不到 filePath，只能靠 Courseware 表按名称+大小反查 LocalId，
    再映射到 Courseware\\<LocalId> 目录。同名多条时取 UpdateTime 最新的。
    """
    import sqlite3
    t = call(s, "get_current_courseware_info", {}, quiet=True)
    try:
        info = json.loads(t)
    except ValueError:
        raise SystemExit("拿不到当前课件信息：%s" % t[:200])
    title, size = info.get("title") or info.get("coursewareName"), info.get("size")
    if not title:
        raise SystemExit("当前没有打开中的课件。")
    db = os.path.join(COURSEWARE_DB_DIR, "CoursewareCacheData.db")
    con = sqlite3.connect(db)
    cur = con.cursor()
    if size:
        cur.execute("SELECT LocalId, Name, Size, UpdateTime FROM Courseware "
                    "WHERE Name=? ORDER BY UpdateTime DESC", (title,))
        rows = cur.fetchall()
        rows = [r for r in rows if r[2] == size] or rows
    else:
        cur.execute("SELECT LocalId, Name, Size, UpdateTime FROM Courseware "
                    "WHERE Name=? ORDER BY UpdateTime DESC", (title,))
        rows = cur.fetchall()
    con.close()
    if not rows:
        raise SystemExit("数据库里找不到课件 %r 的缓存记录。" % title)
    folder = os.path.join(COURSEWARE_DB_DIR, rows[0][0])
    if not os.path.isdir(folder):
        raise SystemExit("缓存目录不存在：%s" % folder)
    print("[current] %s -> %s" % (title, folder))
    return folder


def prune_orphans(slides, res):
    """丢掉没有任何页面引用的资源。否则源里自带的旧副本会白占几十 MB。"""
    used = set()
    for s in slides:
        used.update(re.findall(r"id://([0-9a-fA-F]{8,})", s.decode("utf-8", "ignore")))
    kept, dropped = {}, []
    for (rid, ext), d in res.items():
        if rid in used:
            kept[(rid, ext)] = d
        else:
            dropped.append((rid, ext))
    return kept, dropped


def load_source(src):
    """返回 (root_dir, cleanup)。.enbx 会解压到临时目录。"""
    if os.path.isdir(src):
        return src, None
    tmp = tempfile.mkdtemp(prefix="enbx_src_")
    with zipfile.ZipFile(src) as z:
        z.extractall(tmp)
    return tmp, tmp


def find_one(root, pattern):
    for n in sorted(os.listdir(root)):
        if re.match(pattern, n):
            return os.path.join(root, n)
    return None


def read_xml(path):
    return open(path, "rb").read().decode("utf-8-sig")


def inner(txt, tag, default=""):
    m = re.search(r"<%s>(.*?)</%s>" % (tag, tag), txt, re.S)
    return m.group(1) if m else default


def elements_span(txt):
    """返回**顶层** <Elements> 的 (内容起点, 结束起点)。

    ⚠️ 不能用 `inner(txt,"Elements")`：`<Group>` 内部会再嵌一层 `<Elements>`，
    非贪婪匹配会停在组内那层，页面被拦腰截断。必须按标签深度配对。
    """
    depth = 0
    start = end = None
    for m in re.finditer(r"</?Elements>", txt):
        if m.group(0) == "<Elements>":
            if depth == 0:
                start = m.end()
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                end = m.start()
                break
    return start, end


def top_close_elements(txt):
    """顶层 </Elements> 结束后的偏移；找不到返回 -1。"""
    _, e = elements_span(txt)
    return -1 if e is None else e + len("</Elements>")


def clean_slide_xml(raw, slide_id, width=1280, height=720):
    """把客户端缓存里那一坨（带 SlideAnimationExtension / ThemeId=12）的页面
    归一成干净外壳。不归一的话客户端会弹「课件中部分元素无法解析」且只加载 1 页。
    关键动作：丢弃 SlideAnimationExtension，ThemeId 置 -1。

    ⚠️ 页尾不能写死！`</Elements>` 之后、`</Slide>` 之前的页面级块必须原样保留：
      - `<Activity>`         课堂活动定义（配对/分类/判断的题目与配对关系）
      - `<AnimationOrders>`  进入动画的播放顺序
    写死成「Duration + ThemeForSlide」会把它们整块削掉 —— 活动页只剩卡片没有
    判定逻辑（点着没反应），动画顺序也丢。2026-10-09 第6课配对活动就是被这里削坏的。
    """
    txt = raw.decode("utf-8-sig")
    bg = inner(txt, "Background", "<ColorBrush>#FFFFFFFF</ColorBrush>").strip()
    es, ee = elements_span(txt)
    if es is None:
        raise SystemExit("页面里找不到顶层 <Elements>")
    el = txt[es:ee]

    # 取出页尾（**顶层** </Elements> 之后 → </Slide> 之前），剥掉需要归一的部分，其余原样保留
    tail = txt[top_close_elements(txt):] if top_close_elements(txt) > 0 else ""
    tail = tail.split("</Slide>", 1)[0]
    tail = re.sub(r"<SlideAnimationExtension>.*?</SlideAnimationExtension>", "", tail, flags=re.S)
    tail = re.sub(r"\s*<ThemeForSlide>.*?</ThemeForSlide>", "", tail, flags=re.S)
    duration = inner(tail, "Duration", "5000000")
    tail = re.sub(r"\s*<Duration>.*?</Duration>", "", tail, flags=re.S)
    extra = tail.rstrip()

    return ("""<Slide>
  <Id>%s</Id>
  <Width>%d</Width>
  <Height>%d</Height>
  <KeepIndependentSize>False</KeepIndependentSize>
  <Background>%s</Background>
  <Elements>%s</Elements>
  <Duration>%s</Duration>%s
  <ThemeForSlide>
    <ThemeId>-1</ThemeId>
  </ThemeForSlide>
</Slide>""" % (slide_id, width, height, bg, el, duration, extra)).encode("utf-8")


def video_element(md5, media_name, x=240, y=255, w=800, h=450,
                  loop=False, autoplay=False):
    """真实可用的 <Video> 元素。字段裁剪过：多余字段客户端会当脏数据。"""
    return """<Video>
      <NaturalVideoRotation>0</NaturalVideoRotation>
      <MediaName>%s</MediaName>
      <Source>id://%s</Source>
      <PlayPoints></PlayPoints>
      <Id>%s</Id>
      <X>%d</X><Y>%d</Y><Width>%d</Width><Height>%d</Height>
      <Rotation>0</Rotation><IsLocked>False</IsLocked><CanClone>False</CanClone>
      <Hyperlink></Hyperlink><HasMask>False</HasMask>
      <ElementBehavior><IsLoopPlay>%s</IsLoopPlay><IsAutoPlay>%s</IsAutoPlay><IsCrossSlidePlay>False</IsCrossSlidePlay><StopPlayPageNumber>0</StopPlayPageNumber></ElementBehavior>
      <RotateOrigin>0.5,0.5</RotateOrigin>
      <SaveInfoMetadata><SupportsFallback>True</SupportsFallback><ImportanceLevel>Important</ImportanceLevel></SaveInfoMetadata>
    </Video>""" % (media_name, md5, _nid(), x, y, w, h,
                   "True" if loop else "False", "True" if autoplay else "False")


def video_slide(slide_id, md5, media_name, title, sub):
    """标题 + 副标题 + 视频 的三元素页面。"""
    parts = []
    if title:
        parts.append(_text_xml(100, 60, 1080, 90, [[{"text": title}]],
                               46, "#1E4D3B", align="left", anchor="middle",
                               line_spacing=1.2))
    if sub:
        parts.append(_text_xml(100, 170, 1080, 60, [[{"text": sub}]],
                               26, "#2F6B4F", align="left", anchor="middle",
                               line_spacing=1.2))
    parts.append(video_element(md5, media_name))
    return ("""<Slide>
  <Id>%s</Id>
  <Width>1280</Width>
  <Height>720</Height>
  <KeepIndependentSize>False</KeepIndependentSize>
  <Background>
    <ColorBrush>#FFF7F5EF</ColorBrush>
  </Background>
  <Elements>
    %s
  </Elements>
  <Duration>5000000</Duration>
  <ThemeForSlide>
    <ThemeId>-1</ThemeId>
  </ThemeForSlide>
</Slide>""" % (slide_id, "\n    ".join(parts))).encode("utf-8")


def board_xml(slide_ids, width=1280, height=720):
    items = "\n    ".join("<Item>%s</Item>" % i for i in slide_ids)
    return """<Board>
  <SlideWidth>%d</SlideWidth>
  <SlideHeight>%d</SlideHeight>
  <Slides>
    %s
  </Slides>
  <CopyrightExtension>
    <SaveInfoMetadata>
      <SupportsFallback>True</SupportsFallback>
      <ImportanceLevel>None</ImportanceLevel>
    </SaveInfoMetadata>
  </CopyrightExtension>
  <ThemeForBoard>
    <ThemeId>-1</ThemeId>
  </ThemeForBoard>
</Board>""" % (width, height, items)


def reference_xml(rels):
    lines = []
    for rid, ext, h in rels:
        lines.append("<Relationship>\n      <Id>%s</Id>\n      <Target>Resources\\%s.%s</Target>\n      <Hash>%s</Hash>\n    </Relationship>"
                     % (rid, rid, ext, h))
    return "<Reference>\n  <Relationships>\n    %s\n  </Relationships>\n</Reference>" % "\n    ".join(lines)


# ------------------------------------------------------------------- build ----
def build(src, video, out, name, page="last", title=None, sub=None):
    root, cleanup = load_source(src)
    try:
        board_path = find_one(root, r"Board.*\.xml$")
        doc_path = find_one(root, r"Document.*\.xml$")
        ref_path = find_one(root, r"Reference.*\.xml$")
        if not board_path:
            raise SystemExit("源里找不到 Board.xml：%s" % root)

        board = read_xml(board_path)
        ids = [it.text.strip() for it in ET.fromstring(board).find("Slides").iter("Item")]
        w = int(re.search(r"<SlideWidth>(\d+)", board).group(1))
        h = int(re.search(r"<SlideHeight>(\d+)", board).group(1))
        print("[源] %d 页, %dx%d" % (len(ids), w, h))

        # 页面文件命名有两种：我们自己写的 enbx 是 Slide_<n>.xml，
        # 客户端保存的缓存是 Slide_<n>_<suffix>.xml。两种都兼容。
        # 目录布局也有两种：解压后的 .enbx 在 Slides/ 子目录，客户端缓存目录是扁平的。
        sdir = root
        all_slide = sorted(f for f in os.listdir(sdir)
                           if f.startswith("Slide_") and f.endswith(".xml"))
        if not all_slide and os.path.isdir(os.path.join(root, "Slides")):
            sdir = os.path.join(root, "Slides")
            all_slide = sorted(f for f in os.listdir(sdir)
                               if f.startswith("Slide_") and f.endswith(".xml"))
        plain = sorted((f for f in all_slide if re.fullmatch(r"Slide_\d+\.xml", f)),
                       key=lambda f: int(re.findall(r"\d+", f)[0]))
        suffixed = sorted((f for f in all_slide if re.match(r"Slide_\d+_", f)),
                          key=lambda f: int(re.findall(r"\d+", f)[0]))
        seq = plain if len(plain) >= len(ids) else (suffixed or plain)
        if len(seq) < len(ids):
            raise SystemExit("源里页面文件不足：需要 %d 页，只找到 %d 个（%s）"
                             % (len(ids), len(seq), sdir))
        slide_files = [os.path.join(sdir, seq[n]) for n in range(len(ids))]

        # 资源：解压后的 .enbx 在 Resources/ 子目录，客户端缓存目录是扁平的
        resdir = os.path.join(root, "Resources")
        if not os.path.isdir(resdir):
            resdir = root

        # 资源
        rels, res = [], {}          # rels: [(Id, ext, Hash)]；res: {(Id, ext): bytes}
        if ref_path:
            for r in ET.fromstring(read_xml(ref_path)).iter("Relationship"):
                target = r.findtext("Target") or ""
                rid, ext, hh = r.findtext("Id"), target.split(".")[-1], r.findtext("Hash")
                if not rid:
                    continue
                srcf = os.path.join(resdir, "%s.%s" % (rid, ext))
                if not os.path.exists(srcf):
                    cand = [f for f in os.listdir(resdir) if f.startswith(rid)]
                    if not cand:
                        continue
                    srcf = os.path.join(resdir, cand[0])
                res[(rid, ext)] = open(srcf, "rb").read()
                rels.append((rid, ext, hh or rid))
        idset = {rid for rid, _, _ in rels}
        hash2id = {hh: rid for rid, _, hh in rels}

        def remap(m):
            """页面里引用的可能是内容 md5（我们自己写的 enbx），
            也可能是客户端分配的 Id（缓存）。统一成 Id。"""
            x = m.group(1)
            return "id://" + (x if x in idset else hash2id.get(x, x))

        raw_slides = [open(p, "rb").read() for p in slide_files]
        raw_slides = [re.sub(r"id://([0-9a-fA-F]{8,})", remap,
                             r.decode("utf-8-sig")).encode("utf-8")
                      for r in raw_slides]
        slides = [clean_slide_xml(r, ids[n], w, h) for n, r in enumerate(raw_slides)]

        # 视频资源：源里若已有同内容（Hash==md5），直接复用它的 Id，别塞第二份
        vb = open(video, "rb").read()
        vmd5 = hashlib.md5(vb).hexdigest()
        ext_v = os.path.splitext(video)[1].lstrip(".").lower() or "mp4"
        vid_ref = next((rid for rid, ext, hh in rels if hh == vmd5 and ext == ext_v), None)
        if vid_ref:
            print("[资源] 复用源内同内容视频 Id=%s（不重复占体积）" % vid_ref)
        else:
            vid_ref = vmd5
            res[(vmd5, ext_v)] = vb
            rels.append((vmd5, ext_v, vmd5))
        print("[资源] %d 个（视频 %s，%.1f MB）" % (len(res), vmd5, len(vb) / 1048576))

        # 视频页落位
        media_name = os.path.basename(video)
        if str(page).lower() in ("last", "end", "-1"):
            vid = _nid()
            slides.append(video_slide(vid, vid_ref, media_name, title, sub))
            ids.append(vid)
            pos = len(ids)
        else:
            n = int(page)
            if not (1 <= n <= len(ids)):
                n = len(ids)  # 越界则追加到底
            vid = ids[n - 1]
            slides[n - 1] = video_slide(vid, vid_ref, media_name, title, sub)
            pos = n
        print("[视频页] 第 %d 页" % pos)

        # 剪掉没人引用的资源（源里残留的旧副本）
        res, dropped = prune_orphans(slides, res)
        rels = [(rid, ext, hh) for rid, ext, hh in rels if (rid, ext) in res]
        if dropped:
            print("[剪枝] 丢弃 %d 个无引用资源" % len(dropped))

        doc = read_xml(doc_path) if doc_path else "<Document><Name>x</Name></Document>"
        doc = re.sub(r"<Name>.*?</Name>", "<Name>%s</Name>" % name, doc, count=1)
        sav_path = find_one(root, r"SaveInfoMetadataFile.*\.xml$")
        sav = read_xml(sav_path) if sav_path else "<SaveInfoMetadataFile></SaveInfoMetadataFile>"

        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("Document.xml", BOM + doc.encode("utf-8"))
            z.writestr("Board.xml", BOM + board_xml(ids, w, h).encode("utf-8"))
            for n, s in enumerate(slides):
                z.writestr("Slides/Slide_%d.xml" % n, BOM + s)
            for (rid, ext), d in res.items():
                z.writestr("Resources/%s.%s" % (rid, ext), d)
            z.writestr("Reference.xml", BOM + reference_xml(rels).encode("utf-8"))
            z.writestr("SaveInfoMetadataFile.xml", BOM + sav.encode("utf-8"))
            z.writestr("thumbnail.png", T.thumbnail_png())
        print("[ENBX] %s (%.1f MB, %d 页)" % (out, os.path.getsize(out) / 1048576, len(ids)))
        vcount = 1 + (1 if title else 0) + (1 if sub else 0)
        return out, len(ids), pos, vcount
    finally:
        if cleanup:
            shutil.rmtree(cleanup, ignore_errors=True)


# -------------------------------------------------------------------- mcp -----
def call(s, name, args=None, rid=3, quiet=False):
    st, o = s.tools_call(name, args or {}, rid)
    txt = McpHttpSession.text_of(o)
    if not quiet:
        print("   MCP %s -> %s" % (name, (txt or "").replace("\n", " ")[:150]))
    return txt


def shells(s):
    try:
        return json.loads(call(s, "en_find_shells", {"searchingMode": "All"}, quiet=True)).get("shells") or []
    except Exception:
        return []


def wait_shell(s, name, tries=40):
    for _ in range(tries):
        time.sleep(1.0)
        for x in shells(s):
            if x.get("coursewareName") == name:
                return x.get("id")
    return None


def close_same_name(s, name):
    for x in shells(s):
        if x.get("coursewareName") == name:
            call(s, "close_current_courseware",
                 {"shellId": x.get("id"), "syncBeforeClose": False}, quiet=True)


def main():
    ap = argparse.ArgumentParser(description="给希沃课件自动插入本地视频并同步上云")
    ap.add_argument("--src", required=True,
                    help="源课件缓存目录 / .enbx；传 current 表示「当前打开的课件」")
    ap.add_argument("--video", required=True, help="要插入的 mp4")
    ap.add_argument("--page", default="last", help="视频页位置：last 或页码 N")
    ap.add_argument("--name", default=None, help="云端课件名（不含扩展名）")
    ap.add_argument("--out", default=None, help="输出的 .enbx 路径")
    ap.add_argument("--title", default="看视频")
    ap.add_argument("--sub", default=None)
    ap.add_argument("--sync", action="store_true", help="打开后自动云同步并等待")
    ap.add_argument("--no-open", action="store_true", help="只生成不打开")
    a = ap.parse_args()

    s = None
    if not a.no_open or a.src.lower() == "current":
        port = find_live_port(timeout=3)
        if not port:
            raise SystemExit("希沃 MCP 不可达；请确认客户端已打开并登录。")
        s = McpHttpSession("http://127.0.0.1:%d/mcp" % port, timeout=300)
        s.initialize()
        print("[MCP] port %d" % port)

    src = a.src
    if src.lower() == "current":
        if a.name is None:
            a.name = json.loads(call(s, "get_current_courseware_info", {}, quiet=True)).get("title")
        src = resolve_current(s)

    name = a.name or os.path.splitext(os.path.basename(a.out or "课件"))[0]
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.video)),
                                name + ".enbx")
    # 关键：客户端给本地 enbx 的 coursewareName 取的是 **文件名**（去掉 .enbx），
    # Document.xml 里的 <Name> 会被无视。所以 --out 的文件名才是真正的课件名。
    name = os.path.splitext(os.path.basename(out))[0]
    out, npages, vpos, vcount = build(src, a.video, out, name, a.page, a.title, a.sub)
    if a.no_open:
        return

    print("\n== 关闭同名旧 shell（避免撞车） ==")
    close_same_name(s, name)

    print("\n== os.startfile 打开本地 enbx ==")
    os.startfile(out)
    sh = wait_shell(s, name)
    print("SHELL:", sh)
    if not sh:
        raise SystemExit("等待 shell 超时；客户端可能弹了「部分元素无法解析」对话框。")

    # shell 一注册就立刻读元素会读到空页（视频 10MB，落位慢）。
    # 必须等页数齐 + 视频页非空，否则会把「空视频页」同步上云。
    print("\n== 等待课件加载完成 ==")
    pages, ok, last_good = {}, False, None
    def ready(pp):
        return bool(pp) and pp.get(vpos) and "Video" in pp[vpos] \
            and len(pp[vpos]) >= vcount and len(pp) == npages
    for attempt in range(20):
        time.sleep(2)
        info = json.loads(call(s, "get_current_courseware_info", {"shellId": sh}, quiet=True))
        n = int(info.get("slideCount") or 0)
        pages = {}
        for p in range(1, n + 1):
            t = call(s, "get_elements", {"slideNumber": p, "shellId": sh}, quiet=True)
            try:
                pages[p] = [e.get("type") for e in (json.loads(t).get("elements") or [])]
            except ValueError:
                pages[p] = None
        # 需要连续两次读到齐全的元素，避免把「正在落位」的中间态同步上云
        if ready(pages):
            if last_good == pages:
                ok = True
                break
            last_good = pages
            print("   ...第 %d 次：已齐全，再确认一遍" % (attempt + 1))
            continue
        last_good = None
        print("   ...第 %d 次：%d 页，视频页=%s（期望 %d 元素）"
              % (attempt + 1, n, pages.get(vpos), vcount))

    print("\n== 校验：%d 页（期望 %d） ==" % (len(pages), npages))
    for p in sorted(pages):
        mark = ""
        if p == vpos:
            mark = "  <== 视频页 %s" % ("OK" if pages[p] and "Video" in pages[p] else "缺失!!")
        print("   P%d: %s%s" % (p, pages[p], mark))
    if not ok:
        print("   !! 视频页始终为空；已跳过同步（请检查 enbx 或稍后重试）")

    if a.sync and ok:
        print("\n== 云同步 ==")
        # 刚打开时课件可能还没装好，第一次调 sync 会被静默吞掉；
        # 同时本地新建课件 isCloudCourseware 永远是 false、isSynced 恒 true，
        # 都不能当判据 —— 唯一可靠信号是 sync 工具自己返回的「课件云端 ID：<guid>」。
        remote = None
        for attempt in range(1, 7):
            t = call(s, "sync_current_courseware",
                     {"shellId": sh, "waitUntilSynced": True, "waitSeconds": 180},
                     quiet=True)
            print("   第 %d 次 sync -> %s" % (attempt, (t or "").replace("\n", " ")[:160]))
            m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", t or "")
            if m:
                remote = m.group(0)
                break
            time.sleep(4)
        # 兜底：直接查云端列表确认
        if not remote:
            res = call(s, "search_cloud_courseware", {"keyword": name, "maxResults": 20}, quiet=True)
            if name in res:
                remote = "（云端列表已见同名课件）"
        if remote:
            print("   已上云：%s" % remote)
        else:
            print("   !! 同步未确认，请稍后在客户端手动点一次同步")
            ok = False
    print("\n结论:", "通过" if ok else "存在问题")


if __name__ == "__main__":
    main()
