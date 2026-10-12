#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_cloud_shot.py —— 打开**云端**课件并逐页截图（授课初始态）。

为什么必须用云端而不是本地 enbx：
    背景只存在于客户端内存/云端，不写回本地 enbx —— 本地打开是白底。
    要预览"学生实际看到的版面（含背景）"，只能开云端课件。

用法：
    python _cloud_shot.py "第7课 种子的传播-字体版-含视频" --out "预览目录" \
        [--pages 1,3,7] [--mode Teach|Edit]
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

for v in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY',
          'ALL_PROXY', 'all_proxy'):
    os.environ.pop(v, None)

ap = argparse.ArgumentParser()
ap.add_argument('name', help='云端课件名')
ap.add_argument('--out', required=True)
ap.add_argument('--pages')
ap.add_argument('--mode', default='Teach', choices=['Teach', 'Edit'])
a = ap.parse_args()

s = McpHttpSession('http://127.0.0.1:%d/mcp' % find_live_port(timeout=8),
                   timeout=240)
s.initialize()


def call(name, args=None):
    return McpHttpSession.text_of(s.tools_call(name, args or {})[1])


def shells():
    return json.loads(call('en_find_shells', {'searchingMode': 'all'})).get('shells', [])


def find():
    sid = None
    for x in shells():
        if x.get('coursewareName') == a.name:
            if sid is None or int(x['id']) > int(sid):
                sid = x['id']
    return sid


print('[1] 打开云端课件「%s」' % a.name)
before = {x['id'] for x in shells()}
print('   ', call('open_cloud_courseware', {'coursewareName': a.name})[:200])

sid = None
for _ in range(60):
    time.sleep(1)
    sid = find()
    if sid:
        break
if not sid:
    raise SystemExit('没找到已打开的云端课件 shell')

# 等页面落位：连续两次元素数一致
info = json.loads(call('get_current_courseware_info', {'shellId': sid}))
n = int(info.get('slideCount') or 0)
print('    shell=%s 页数=%d 模式=%s'
      % (sid, n, (info.get('shellContext') or {}).get('workingMode')))

# 注意：switch_to_display_board_mode 是「板书笔模式(选择/笔/橡皮)」，不是视图切换。
# 云端课件打开后 shellContext.workingMode 本就是 Display（放映态），无需再切。
if a.mode == 'Edit':
    print('    （提示：需要备课视图时请改用 enbx_shot.py 打开本地 enbx）')
time.sleep(2)

os.makedirs(a.out, exist_ok=True)
want = ([int(x) for x in a.pages.split(',')] if a.pages else list(range(1, n + 1)))


def grab(pno, path):
    """截图。

    坑：get_slide_screenshot 成功时返回的是 image content（base64），
    不能走 text_of()（那是给 text content 用的，会抛异常）。
    另外 expectedPngImageFilePath 有时不生效 —— 两种落盘路径都兜住。
    """
    res = s.tools_call('get_slide_screenshot',
                       {'slideNumber': pno, 'shellId': sid,
                        'expectedPngImageFilePath': path})
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return True
    try:
        body = res[1]['result']
        for item in body.get('content') or []:
            data = item.get('data')
            if item.get('type') == 'image' and data:
                import base64
                with open(path, 'wb') as fh:
                    fh.write(base64.b64decode(data))
                return True
    except Exception as exc:
        print('      [warn] 取图失败：%s' % exc)
    return False


ok = 0
for p in want:
    path = os.path.abspath(os.path.join(a.out, 'P%02d.png' % p))
    try:
        s.tools_call('goto_slide', {'slideNumber': p, 'shellId': sid})
    except Exception as exc:
        print('      [warn] goto_slide %d 失败：%s' % (p, exc))
    time.sleep(0.8)
    good = grab(p, path)
    ok += good
    print('  P%-2d %s %s KB' % (p, 'OK' if good else 'FAIL',
                                (os.path.getsize(path) // 1024) if good else 0))
    time.sleep(0.3)
print('完成：%d 张 → %s' % (ok, a.out))
