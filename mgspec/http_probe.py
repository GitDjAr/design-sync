#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""http_probe.py — 自测用：在后台线程起服务，用 urllib 打一遍，再退出。"""
import json
import os
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server as srv_mod  # noqa: E402

PORT = 45871
srv_mod.STATE["root"] = HERE
srv_mod.Handler.log_message = lambda *a, **k: None

httpd = ThreadingHTTPServer(("127.0.0.1", PORT), srv_mod.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % PORT


def get(path):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return r.read().decode("utf-8")


def post(path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read().decode("utf-8")


print("GET /health  ->", get("/health"))
print("GET /spec    ->", get("/spec?path=fixture.sketch&format=text").splitlines()[1][:80])
print("GET /find    ->", get("/find?path=fixture.sketch&q=Avatar").splitlines()[2][:80])
out = json.loads(post("/compare", {"design": "fixture.sketch", "computed": "fixture.computed.json"}))
print("POST /compare-> %d diffs" % out["count"])
print("GET /tools   ->", len(json.loads(get("/tools"))), "tools")
httpd.shutdown()
print("http probe ok")
