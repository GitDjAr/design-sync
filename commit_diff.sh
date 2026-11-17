#!/usr/bin/env bash
# commit_diff.sh — 提交 spec_diff
set -eu
cd "$(dirname "$0")"
rm -rf mgspec/__pycache__
bash mgspec/check_diff.sh >/tmp/_cd.log 2>&1 && echo "spec_diff OK" || echo "spec_diff: has diffs (expected)"
grep -q 'fixture.plugin' .gitignore || printf 'fixture.plugin.json\nfixture.plugin.v2.json\n' >> .gitignore
git add -A
if git diff --cached --quiet; then echo "nothing to commit"; else
  git commit -q -m "feat: spec_diff — track design revisions as reviewable json diffs

- match layers by path so moves do not misalign
- watch radius / padding / gap / axis / fontSize / lineHeight / letterSpacing / box / visibility
- --md for PR descriptions, --json for tooling, exit 1 when something changed"
  echo committed
fi
git log --oneline | head -5
