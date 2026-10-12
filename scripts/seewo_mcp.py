#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seewo_mcp.py — 希沃白板 MCP 命令行小工具（免去每次手写握手）。

用法：
    python seewo_mcp.py list                       # 列出工具
    python seewo_mcp.py call <tool> '<json args>'  # 调用工具
    python seewo_mcp.py info                       # 当前课件信息
    python seewo_mcp.py elements [页码]             # 列当前页/指定页元素
    python seewo_mcp.py find                        # 列所有 shell
    python seewo_mcp.py pages                       # 逐页列出元素类型

注意：调用前必须清掉代理环境变量（否则 7916 会假死 502）：
    unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import seewo_config                                     # noqa: E402
seewo_config.ensure_official_paths("mcp")
from mcp_client import McpHttpSession, find_live_port  # noqa: E402

for _v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_v, None)


def connect():
    port = find_live_port(timeout=3)
    if not port:
        raise SystemExit("找不到可用的希沃 MCP 端口；请确认希沃白板客户端已打开并登录。")
    s = McpHttpSession("http://127.0.0.1:%d/mcp" % port)
    s.initialize()
    print("[MCP] port=%d" % port, file=sys.stderr)
    return s


def call(s, name, args=None):
    st, o = s.tools_call(name, args or {})
    return McpHttpSession.text_of(o)


def as_json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def find_shell_by_name(s, name, tries=12, delay=1.0):
    """本地 enbx / 云课件打开后 shell 注册有延迟，需轮询；且本地 enbx 的
    coursewareName 用的是「文件名」。"""
    for _ in range(tries):
        st, o = s.tools_call("en_find_shells", {"searchingMode": "all"})
        ids = McpHttpSession.find_shells_named(o, name)
        if ids:
            return ids
        time.sleep(delay)
    return []


def cmd_pages(s, shell=None):
    info = call(s, "get_current_courseware_info", {"shellId": shell} if shell else {})
    data = as_json(info) or {}
    n = data.get("slideCount") or 0
    print("课件: %s | 页数: %s | 云: %s | 已同步: %s"
          % (data.get("title") or data.get("coursewareName"), n,
             data.get("isCloudCourseware"), data.get("isSynced")))
    for p in range(1, int(n) + 1):
        args = {"slideNumber": p}
        if shell:
            args["shellId"] = shell
        t = call(s, "get_elements", args)
        d = as_json(t) or {}
        els = d.get("elements") or []
        print("  P%d: %s" % (p, [e.get("type") for e in els]))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    s = connect()
    if cmd == "list":
        st, o = s.tools_list()
        for t in (o or {}).get("result", {}).get("tools", []):
            print(t["name"])
    elif cmd == "call":
        print(call(s, sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}))
    elif cmd == "info":
        print(call(s, "get_current_courseware_info", {}))
    elif cmd == "find":
        print(call(s, "en_find_shells", {"searchingMode": "all"}))
    elif cmd == "elements":
        args = {"slideNumber": int(sys.argv[2])} if len(sys.argv) > 2 else {}
        print(call(s, "get_elements", args))
    elif cmd == "pages":
        cmd_pages(s, sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        print("未知子命令: %s" % cmd)
        print(__doc__)


if __name__ == "__main__":
    main()
