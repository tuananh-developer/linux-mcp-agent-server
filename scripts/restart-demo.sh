#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

if command -v systemctl >/dev/null 2>&1 && systemctl cat linux-mcp-agent.service >/dev/null 2>&1; then
  printf 'Restarting the installed systemd MCP service...\n'
  sudo systemctl restart linux-mcp-agent.service
  exec bash "$ROOT/scripts/start-demo.sh"
fi

printf 'Restarting the user-managed demo MCP process...\n'
bash "$ROOT/scripts/stop-demo.sh"
exec bash "$ROOT/scripts/start-demo.sh"
