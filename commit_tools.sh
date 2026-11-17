#!/usr/bin/env bash
# commit_tools.sh — 提交 raw postMessage 修正 + 工具清单
set -eu
cd "$(dirname "$0")"
rm -rf mgspec/__pycache__
bash mgspec/check_syntax.sh
git add -A
if git diff --cached --quiet; then echo "nothing to commit"; else
  git commit -q -m "fix: use raw postMessage for MasterGo; add ecosystem tool map

- MasterGo UI bridge uses raw parent.postMessage, not Figma's { pluginMessage } wrapper
- keep pluginMessage fallback on the receive side for Figma compatibility
- README: marketplace JSON exporters, mastergo-skills, mastergo-mcp-plugin,
  DIY thin client via MG_MCP_TOKEN, and fallback verification tools"
  echo committed
fi
export GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10"
git push origin main 2>&1 | tail -4
git log --oneline | head -3
