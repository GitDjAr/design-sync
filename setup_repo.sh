#!/usr/bin/env bash
# setup_repo.sh — 初始化 design-sync 仓库并提交
set -eu
cd "$(dirname "$0")"

rm -f probe.sh probe2.sh probe3.sh
rm -rf mgspec/__pycache__

cat > .gitignore <<'EOF'
__pycache__/
*.pyc
*.pyo
node_modules/
.DS_Store

# 自测产物（由 make_fixture.py 生成）
fixture.sketch
fixture.spec.json
fixture.computed.json
*.spec.json
*.computed.json
*.mg

# 本地设计稿缓存
designs/*.sketch
designs/*.mg
designs/out/
EOF

mkdir -p designs
[ -f designs/.gitkeep ] || : > designs/.gitkeep

if [ ! -d .git ]; then
  git init -q -b main
fi
git config core.filemode false
git config core.autocrlf false
git config user.name "$(git config --global user.name)"
git config user.email "$(git config --global user.email)"

git add -A
if git diff --cached --quiet; then
  echo "nothing to commit"
else
  git commit -q -m "feat: design/code consistency toolchain without MasterGo MCP

- sketch_reader: .sketch -> spec json (+ visual padding/gap derivation, --lint export health check)
- mg_reader: .mg zip/json harvest with padding default caveats
- compare: design spec vs browser computed style diff with root-cause hints
- server: self-hosted HTTP + MCP(stdio) service, zero dependency
- capture-computed.mjs: Playwright computed style capture"
  echo "committed"
fi

REMOTE=git@github.com:GitDjAr/design-sync.git
git remote remove origin 2>/dev/null || true
git remote add origin "$REMOTE"
echo "remote -> $(git remote get-url origin)"
git log --oneline -1
