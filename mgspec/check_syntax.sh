#!/usr/bin/env bash
# check_syntax.sh — 校验插件 JS 与 manifest
set -u
cd "$(dirname "$0")/.."

if node --check mastergo-plugin/main.js; then
  echo "main.js syntax OK"
else
  echo "main.js syntax FAIL"
  exit 1
fi

python3 - <<'PY'
import json
m = json.load(open('mastergo-plugin/manifest.json'))
assert m['api'] == '1.0.0', 'api 必须是 1.0.0'
assert 'main' in m and 'ui' in m
print('manifest.json OK:', m['name'], '| menu items:', len(m.get('menu', [])))
PY

# 抽出 ui.html 里的 <script> 做语法检查
python3 - <<'PY'
import re, pathlib
html = pathlib.Path('mastergo-plugin/ui.html').read_text(encoding='utf-8')
m = re.search(r'<script>(.*?)</script>', html, re.S)
assert m, 'ui.html 里找不到 <script>'
pathlib.Path('/tmp/_ui_check.js').write_text(m.group(1), encoding='utf-8')
print('ui script extracted:', len(m.group(1)), 'chars')
PY

if node --check /tmp/_ui_check.js; then
  echo "ui.html script syntax OK"
else
  echo "ui.html script syntax FAIL"
  exit 1
fi
