#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/linux-mcp-agent"
PID_FILE="$STATE_DIR/demo-server.pid"
CURRENT_UID="$(id -u)"
declare -a CANDIDATE_PIDS=()
declare -A SEEN_PIDS=()

add_candidate() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  [[ -n "${SEEN_PIDS[$pid]:-}" ]] && return 0
  SEEN_PIDS["$pid"]=1
  CANDIDATE_PIDS+=("$pid")
}

is_this_demo_process() {
  local pid="$1" command_line process_root
  [[ -r "/proc/$pid/cmdline" && -r "/proc/$pid/cwd" ]] || return 1
  command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  [[ "$command_line" == *"-m linux_mcp_agent"* ]] || return 1
  process_root="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  [[ "$process_root" == "$ROOT" ]]
}

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE")"
  if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
    printf 'Invalid PID file: %s\n' "$PID_FILE" >&2
    exit 1
  fi

  if kill -0 "$pid" 2>/dev/null; then
    if ! is_this_demo_process "$pid"; then
      printf 'Refusing to stop PID %s: it is not the MCP process launched from %s.\n' "$pid" "$ROOT" >&2
      exit 1
    fi
    add_candidate "$pid"
  else
    rm -f "$PID_FILE"
    printf 'Stale PID file removed.\n'
  fi
fi

# Recover safely when the demo process is alive but its PID file was lost.
while IFS= read -r pid; do
  [[ -n "$pid" ]] || continue
  if is_this_demo_process "$pid"; then
    add_candidate "$pid"
  fi
done < <(pgrep -u "$CURRENT_UID" -f '[p]ython.*-m linux_mcp_agent' || true)

if (( ${#CANDIDATE_PIDS[@]} == 0 )); then
  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet linux-mcp-agent.service; then
    printf 'MCP is managed by systemd; use scripts/restart-demo.sh to restart it.\n'
    exit 0
  fi
  printf 'No demo-managed MCP process was found.\n'
  exit 0
fi

for pid in "${CANDIDATE_PIDS[@]}"; do
  printf 'Stopping demo MCP process (PID %s)...\n' "$pid"
  kill -INT "$pid"

  stopped=false
  for _ in $(seq 1 10); do
    if ! kill -0 "$pid" 2>/dev/null; then
      stopped=true
      break
    fi
    sleep 1
  done

  if [[ "$stopped" != "true" ]]; then
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 5); do
      if ! kill -0 "$pid" 2>/dev/null; then
        stopped=true
        break
      fi
      sleep 1
    done
  fi

  if [[ "$stopped" != "true" ]]; then
    printf 'ERROR: MCP process %s did not stop cleanly; refusing to remove its PID file.\n' "$pid" >&2
    exit 1
  fi
done

rm -f "$PID_FILE"
printf 'Demo MCP process stopped.\n'
