#!/usr/bin/env bash
# ls_work.sh — 看 WSL 里的项目目录
set -u
echo "== ~ =="
ls -1 ~ | head -20
echo "== ~/work =="
ls -1 ~/work 2>/dev/null || echo "(none)"
echo "== ~/project =="
ls -1a ~/project 2>/dev/null | head -20 || echo "(none)"
echo "== find dirs named project =="
find ~ -maxdepth 3 -type d -iname "*project*" 2>/dev/null | head -20
echo "== node/pnpm =="
bash -lc 'node -v; pnpm -v' 2>/dev/null || true
echo "== fnm =="
ls -1 ~/.local/share/fnm/node-versions 2>/dev/null | head
