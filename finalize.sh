#!/usr/bin/env bash
# finalize.sh — 收尾：清掉临时脚本，提交 README/selftest 变更
set -eu
cd "$(dirname "$0")"

git rm -q --cached setup_repo.sh 2>/dev/null || true
rm -f setup_repo.sh push.sh
rm -rf mgspec/__pycache__

grep -q 'setup_repo.sh' .gitignore || printf 'setup_repo.sh\npush.sh\n' >> .gitignore

git add -A
if git diff --cached --quiet; then
  echo "nothing to commit"
else
  git commit -q -m "docs: export-fidelity caveats + --lint health check

- explain the two Sketch export modes and what each one loses
- add sketch_reader --lint: radius/padding/font anomalies, missing fonts
- extend selftest with lint stage"
  echo committed
fi
git log --oneline
echo "--- status ---"
git status --short
