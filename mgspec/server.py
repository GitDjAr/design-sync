#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — 自己搭的设计稿服务（替代 MasterGo 官方 MCP）。

两种运行形态，同一份代码：
  HTTP  : python3 server.py http --port 4310 --root ./designs
          GET  /spec?path=a.sketch&ai=1
          GET  /find?path=a.sketch&q=button
          POST /compare  {design, computed}
  MCP   : python3 server.py mcp --root ./designs
          stdio JSON-RPC 2.0，直接贴到 Cursor / Claude / Codex 的 mcpServers 配置里

工具暴露给 AI 的只有三个，够用且省 token：
  design_spec   读整份设计规格（可要求 AI 友好文本）
  design_find   按图层名/路径查单个节点
  design_compare 设计与实现对账
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import sketch_reader  # noqa: E402
import mg_reader      # noqa: E402
import compare as cmp_mod  # noqa: E402

STATE = {"root": "."}


def abspath(p):
    if os.path.isabs(p):
        return p
    return os.path.join(STATE["root"], p)


def load_spec(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".sketch":
        return sketch_reader.read_sketch(path)
    if ext == ".mg":
        return mg_reader.read_mg(path)
    if ext == ".json":
        return json.load(open(path, encoding="utf-8"))
    raise ValueError("不支持的扩展名: " + ext)


def tool_design_spec(args):
    spec = load_spec(abspath(args["path"]))
    if args.get("page"):
        spec["pages"] = [p for p in spec["pages"] if p.get("page") == args["page"]]
    if args.get("format") == "text":
        # mg 有自己的一套字段，其余（sketch / 插件导出）结构一致，共用同一套渲染
        if spec.get("kind") == "mg":
            return mg_reader.to_ai_text(spec)
        return sketch_reader.to_ai_text(spec)
    return json.dumps(spec, ensure_ascii=False, indent=1)


def tool_design_find(args):
    spec = load_spec(abspath(args["path"]))
    q = str(args.get("q", "")).lower()
    hits = []
    for pg in spec.get("pages", []):
        for n in pg.get("nodes", []):
            hay = (str(n.get("name")) + " " + str(n.get("path"))).lower()
            if q and q in hay:
                hits.append(dict(n, page=pg.get("page")))
    if not hits:
        return "没有匹配的图层：%s" % q
    return json.dumps(hits[:20], ensure_ascii=False, indent=1)


def tool_design_compare(args):
    spec = load_spec(abspath(args["design"]))
    comp = json.load(open(abspath(args["computed"]), encoding="utf-8"))
    idx = cmp_mod.build_index(spec)
    out = []
    for c in comp.get("nodes", []):
        d = cmp_mod.match(c, idx)
        if not d:
            continue
        for prop, dv, cv, kind in cmp_mod.diff_node(d, c, args.get("tol", 0.5)):
            out.append({"layer": d.get("name"), "prop": prop, "design": dv,
                        "actual": cv, "hint": cmp_mod.explain(prop, c)})
    return json.dumps({"diffs": out, "count": len(out)}, ensure_ascii=False, indent=1)


TOOLS = [
    {
        "name": "design_spec",
        "description": "读取 MasterGo 导出的 .sketch/.mg 设计文件，返回图层规格 JSON（圆角/自动布局 padding/间距/字号）。format=text 返回省 token 的紧凑文本。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对 root 的文件路径"},
                "page": {"type": "string"},
                "format": {"type": "string", "enum": ["json", "text"]},
            },
            "required": ["path"],
        },
    },
    {
        "name": "design_find",
        "description": "按图层名/路径模糊查单个节点，返回其框、圆角、padding、gap、文字样式。",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "q": {"type": "string"}},
            "required": ["path", "q"],
        },
    },
    {
        "name": "design_compare",
        "description": "设计规格与浏览器 computed style（capture-computed.mjs 产出）对账，输出 border-radius/padding/margin/font-size 差异及根因提示。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "design": {"type": "string"},
                "computed": {"type": "string"},
                "tol": {"type": "number"},
            },
            "required": ["design", "computed"],
        },
    },
]

HANDLERS = {"design_spec": tool_design_spec, "design_find": tool_design_find,
            "design_compare": tool_design_compare}


# ---------------------------------------------------------------- MCP stdio
def mcp_send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def mcp_serve():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            mcp_send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "design-sync", "version": "1.0.0"},
            }})
        elif method in ("notifications/initialized", "initialized"):
            continue
        elif method == "tools/list":
            mcp_send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            p = msg.get("params") or {}
            name = p.get("name")
            args = p.get("arguments") or {}
            fn = HANDLERS.get(name)
            if not fn:
                mcp_send({"jsonrpc": "2.0", "id": mid,
                          "error": {"code": -32601, "message": "unknown tool " + str(name)}})
                continue
            try:
                text = fn(args)
                mcp_send({"jsonrpc": "2.0", "id": mid,
                          "result": {"content": [{"type": "text", "text": text}]}})
            except Exception as e:
                mcp_send({"jsonrpc": "2.0", "id": mid,
                          "result": {"content": [{"type": "text", "text": "error: %s" % e}],
                                     "isError": True}})
        elif mid is not None:
            mcp_send({"jsonrpc": "2.0", "id": mid,
                      "error": {"code": -32601, "message": "unknown method " + str(method)}})


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    def _ok(self, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _err(self, code, msg):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(str(msg).encode("utf-8"))

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/health":
                return self._ok('{"ok":true}')
            if u.path == "/spec":
                return self._ok(tool_design_spec(q))
            if u.path == "/find":
                return self._ok(tool_design_find(q), "text/plain; charset=utf-8")
            if u.path == "/tools":
                return self._ok(json.dumps(TOOLS, ensure_ascii=False, indent=1))
            return self._err(404, "no route " + u.path)
        except Exception as e:
            return self._err(500, e)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            if u.path == "/compare":
                return self._ok(tool_design_compare(body))
            return self._err(404, "no route " + u.path)
        except Exception as e:
            return self._err(500, e)

    def log_message(self, fmt, *args):
        sys.stderr.write("[design-sync] " + (fmt % args) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["http", "mcp"])
    ap.add_argument("--port", type=int, default=4310)
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    STATE["root"] = os.path.abspath(a.root)
    if a.mode == "mcp":
        mcp_serve()
    else:
        srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
        sys.stderr.write("design-sync http://127.0.0.1:%d  root=%s\n" % (a.port, STATE["root"]))
        srv.serve_forever()


if __name__ == "__main__":
    main()
