#!/usr/bin/env bash
set -Eeuo pipefail

PID_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/linux-mcp-agent/demo-server.pid"

if [[ ! -f "$PID_FILE" ]]; then
  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet linux-mcp-agent.service; then
    printf 'MCP is managed by systemd. Stop it with: sudo systemctl stop linux-mcp-agent.service\n'
    exit 0
  fi
  printf 'No demo-managed MCP process was found.\n'
  exit 0
fi

pid="$(cat "$PID_FILE")"
if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
  printf 'Invalid PID file: %s\n' "$PID_FILE" >&2
  exit 1
fi

if ! kill -0 "$pid" 2>/dev/null; then
  rm -f "$PID_FILE"
  printf 'Stale PID file removed.\n'
  exit 0
fi

command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
if [[ "$command_line" != *"-m linux_mcp_agent"* ]]; then
  printf 'Refusing to stop PID %s because it is not the expected MCP process.\n' "$pid" >&2
  exit 1
fi

kill -INT "$pid"
for _ in $(seq 1 10); do
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$PID_FILE"
    printf 'Demo MCP process stopped.\n'
    exit 0
  fi
  sleep 1
done

kill -TERM "$pid" 2>/dev/null || true
rm -f "$PID_FILE"
printf 'Demo MCP process terminated.\n'
