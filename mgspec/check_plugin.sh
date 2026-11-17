#!/usr/bin/env bash
# check_plugin.sh — 验证插件输出结构能被 compare / server 消费
set -u
cd "$(dirname "$0")"

echo "== compare (plugin spec vs computed) =="
python3 compare.py fixture.plugin.json fixture.computed.json
echo "exit=$?"

cat > /tmp/_p.py <<'PY'
import json, sys
sys.path.insert(0, '.')
import sketch_reader
spec = json.load(open('fixture.plugin.json'))
print('== to_ai_text ==')
print(sketch_reader.to_ai_text(spec))
PY
python3 /tmp/_p.py
