#!/usr/bin/env bash
# check_diff.sh — 验证 spec_diff
set -u
cd "$(dirname "$0")"
python3 spec_diff.py fixture.plugin.json fixture.plugin.v2.json
echo "exit=$?"
echo
echo "== markdown 视图 =="
python3 spec_diff.py fixture.plugin.json fixture.plugin.v2.json --md | head -30
echo
echo "== 同一份文件应无变更 =="
python3 spec_diff.py fixture.plugin.json fixture.plugin.json
echo "exit=$?"
