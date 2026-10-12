#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""enbx_shot.py —— 打开本地 .enbx 并逐页截图。

- 默认抓**备课(Edit)视图**：带 Click 动画的元素会全部显示出来 ⇒ 用来检查版面有没有错位。
- 想看「授课初始态」（动画元素隐藏）请加 --mode Teach。

用法：
    python enbx_shot.py "课件.enbx" --out "预览目录" [--pages 3,6,9,14] [--mode Edit]

注意：
  * 打开 .enbx 必须 os.startfile（en_sys 会把它当可执行文件报错）。
  * 同名 shell 会撞车，脚本会先关掉同名 shell。
  * 截图前要等页面落位（连续两次元素数一致）。
"""
import argparse
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seewo_config                                     # noqa: E402
seewo_config.ensure_official_paths("mcp")
from mcp_client import McpHttpSession, find_live_port   # noqa: E402

for v in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'all_proxy'):
    os.environ.pop(v, None)

ap = argparse.ArgumentParser()
ap.add_argument('enbx')
ap.add_argument('--out', required=True, help='截图输出目录')
ap.add_argument('--pages', help='只截这几页，如 3,6,9 （默认全部）')
ap.add_argument('--mode', default='Edit', choices=['Edit', 'Teach'])
ap.add_argument('--expect', type=int, default=0, help='期望页数，用于判断落位完成')
ap.add_argument('--keep', action='store_true')
a = ap.parse_args()

ENBX = os.path.abspath(a.enbx)
NAME = os.path.splitext(os.path.basename(ENBX))[0]
# 必须绝对路径：截图由希沃客户端进程落盘，它按自己的 CWD 解析相对路径 ⇒ 会静默失败
a.out = os.path.abspath(a.out)
os.makedirs(a.out, exist_ok=True)
want = set(int(x) for x in a.pages.split(',')) if a.pages else None

port = find_live_port(timeout=5)
if not port:
    raise SystemExit('希沃 MCP 不可达（7916）')
s = McpHttpSession('http://127.0.0.1:%d/mcp' % port, timeout=180)
s.initialize()


def call(n, ar=None):
    st, o = s.tools_call(n, ar or {})
    return McpHttpSession.text_of(o)


def shells():
    try:
        return json.loads(call('en_find_shells', {'searchingMode': 'all'})).get('shells') or []
    except Exception:
        return []


for x in shells():
    if x.get('coursewareName') == NAME:
        call('close_current_courseware', {'shellId': x['id'], 'syncBeforeClose': False})
time.sleep(3)

print('[1] 打开 %s（%s 视图）' % (NAME, a.mode))
os.startfile(ENBX)
sid = None
for i in range(60):
    time.sleep(1)
    for x in shells():
        if x.get('coursewareName') == NAME and x.get('workingMode') == a.mode:
            if sid is None or int(x['id']) > int(sid):
                sid = x['id']
    if sid:
        print('    shell=%s (%d 次)' % (sid, i + 1))
        break
if not sid:
    raise SystemExit('未找到 shell（mode=%s）；客户端可能弹了「部分元素无法解析」对话框' % a.mode)

print('[2] 等落位 ...')
n, last = 0, None
for _ in range(25):
    time.sleep(2)
    try:
        n = int(json.loads(call('get_current_courseware_info', {'shellId': sid})).get('slideCount') or 0)
    except ValueError:
        continue
    cur = []
    for p in range(1, n + 1):
        try:
            cur.append(len(json.loads(call('get_elements', {'slideNumber': p, 'shellId': sid})).get('elements') or []))
        except ValueError:
            cur.append(None)
    if n and cur == last and (not a.expect or n == a.expect):
        break
    last = cur
print('    页数=%d' % n)

print('[3] 截图 → %s' % a.out)
ok = 0
for p in range(1, n + 1):
    if want and p not in want:
        continue
    path = os.path.join(a.out, 'P%02d.png' % p)
    call('get_slide_screenshot', {'slideNumber': p, 'shellId': sid,
                                  'expectedPngImageFilePath': path})
    good = os.path.isfile(path)
    ok += good
    print('  P%-2d %s %s' % (p, 'OK' if good else 'FAIL',
                             ('%d KB' % (os.path.getsize(path) // 1024)) if good else ''))
    time.sleep(0.4)

if not a.keep:
    call('close_current_courseware', {'shellId': sid, 'syncBeforeClose': False})
print('完成：%d 张' % ok)
