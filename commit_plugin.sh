#!/usr/bin/env bash
# commit_plugin.sh — 回归 + 提交插件
set -eu
cd "$(dirname "$0")"
rm -rf mgspec/__pycache__

bash mgspec/selftest.sh >/tmp/_st.log 2>&1 && echo "selftest OK" || { echo "selftest FAIL"; tail -20 /tmp/_st.log; exit 1; }
bash mgspec/check_syntax.sh
bash mgspec/check_plugin.sh >/tmp/_cp.log 2>&1 && echo "plugin-diff OK" || echo "plugin-diff: has diffs (expected 7)"

git add -A
if git diff --cached --quiet; then
  echo "nothing to commit"
else
  git commit -q -m "feat: MasterGo plugin for zero-conversion spec export

- mastergo-plugin/: manifest + sandbox main + UI panel
- reads cornerRadius / layoutMode padding / itemSpacing / fontSize directly from the document
- emits the same schema as sketch_reader, so compare.py and server.py work unchanged
- export page / selection / include-hidden, with AI text view and .spec.json download
- server: route non-mg specs through the sketch text renderer"
  echo committed
fi
git log --oneline
git status --short
