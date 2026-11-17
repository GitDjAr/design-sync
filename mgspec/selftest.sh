#!/usr/bin/env bash
# selftest.sh — 一键自测：解析 -> HTTP -> MCP
set -u
cd "$(dirname "$0")"

echo "== 1. build fixture =="
python3 make_fixture.py
python3 sketch_reader.py fixture.sketch -o fixture.spec.json
python3 sketch_reader.py fixture.sketch --ai | head -6

echo
echo "== 2. lint =="
python3 sketch_reader.py fixture.sketch --lint | head -14

echo
echo "== 3. compare =="
python3 compare.py fixture.spec.json fixture.computed.json | head -12

echo
echo "== 4. http server =="
python3 http_probe.py

echo
echo "== 5. mcp stdio =="
printf '%s\n%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"design_find","arguments":{"path":"fixture.sketch","q":"Avatar"}}}' \
  | python3 server.py mcp --root . | head -4

echo
echo "selftest done"
