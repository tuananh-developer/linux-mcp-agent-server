#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$ROOT/deploy/compose"
COMPOSE_FILE="$COMPOSE_DIR/compose.yaml"
COMPOSE_ENV_FILE="${LINUX_MCP_COMPOSE_ENV_FILE:-$COMPOSE_DIR/.env}"
SERVER_ENV_FILE="${LINUX_MCP_SERVER_ENV_FILE:-}"
SYSTEMD_ENV_FILE="${LINUX_MCP_SYSTEMD_ENV_FILE:-/etc/linux-mcp-agent/server.env}"
MCP_PORT_OVERRIDE="${MCP_PORT:-}"
SYSTEMD_MANAGED=false
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/linux-mcp-agent"
CONFIG_DIR="$HOME/.config/linux-mcp-agent"
PID_FILE="$STATE_DIR/demo-server.pid"
LOG_FILE="$STATE_DIR/demo-server.log"
CA_FILE="$CONFIG_DIR/caddy-root.crt"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

read_config_value() {
  local file="$1" key="$2" line value
  if [[ -r "$file" ]]; then
    line="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$file" | tail -n 1 || true)"
  else
    line="$(sudo grep -E "^[[:space:]]*${key}[[:space:]]*=" "$file" 2>/dev/null | tail -n 1 || true)"
  fi
  [[ -n "$line" ]] || return 0
  value="${line#*=}"
  value="${value#\"}"
  value="${value%\"}"
  value="${value#\'}"
  value="${value%\'}"
  printf '%s\n' "$value"
}

compose_env_value() {
  local key="$1" fallback="$2" value
  value="$(read_config_value "$COMPOSE_ENV_FILE" "$key" || true)"
  printf '%s\n' "${value:-$fallback}"
}

wait_for_keycloak() {
  local container_id status
  container_id="$("${compose[@]}" ps -q keycloak)"
  [[ -n "$container_id" ]] || fail "Keycloak container was not created."

  printf 'Waiting for Keycloak health check'
  for _ in $(seq 1 90); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || true)"
    case "$status" in
      healthy)
        printf ' ready\n'
        return 0
        ;;
      unhealthy|exited|dead)
        printf '\n'
        "${compose[@]}" logs --tail=60 keycloak >&2
        fail "Keycloak is $status. Check the logs above."
        ;;
    esac
    printf '.'
    sleep 2
  done
  printf '\n'
  "${compose[@]}" logs --tail=60 keycloak >&2
  fail "Timed out waiting for Keycloak to become healthy."
}

wait_for_mcp() {
  local url="http://127.0.0.1:${MCP_PORT}/healthz"
  printf 'Waiting for MCP health check on port %s' "$MCP_PORT"
  for _ in $(seq 1 30); do
    if curl --silent --show-error --fail --max-time 2 "$url" >/dev/null 2>&1; then
      printf ' ready\n'
      return 0
    fi
    printf '.'
    sleep 1
  done
  printf '\n'
  return 1
}

ensure_mcp_running() {
  if wait_for_mcp; then
    printf 'Reusing MCP service at 127.0.0.1:%s\n' "$MCP_PORT"
    return 0
  fi

  if [[ "$SYSTEMD_MANAGED" == "true" ]]; then
    printf 'Restarting installed linux-mcp-agent systemd service...\n'
    sudo systemctl restart linux-mcp-agent.service
    wait_for_mcp || {
      sudo systemctl status --no-pager linux-mcp-agent.service >&2 || true
      sudo journalctl -u linux-mcp-agent.service -n 80 --no-pager >&2 || true
      fail "MCP did not become healthy on port $MCP_PORT after the systemd restart."
    }
    return 0
  fi

  [[ -n "$SERVER_ENV_FILE" && -r "$SERVER_ENV_FILE" ]] ||
    fail "MCP is not running and no readable server.env was found. Create ~/.config/linux-mcp-agent/server.env or install linux-mcp-agent.service."

  [[ "${AUTH_MODE:-}" == "keycloak" ]] ||
    fail "Server environment must set AUTH_MODE=keycloak."

  command -v uv >/dev/null 2>&1 || fail "uv is required to launch the MCP server."
  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR"
  if [[ -f "$PID_FILE" ]]; then
    local old_pid
    old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ "$old_pid" =~ ^[0-9]+$ ]] && kill -0 "$old_pid" 2>/dev/null; then
      fail "Demo MCP process PID $old_pid still exists but is not healthy. Inspect $LOG_FILE before starting another process."
    fi
    rm -f "$PID_FILE"
  fi

  local python_bin
  python_bin="$(uv run python -c 'import sys; print(sys.executable)')"
  printf 'Launching MCP in background with %s\n' "$SERVER_ENV_FILE"
  printf 'Log file: %s\n' "$LOG_FILE"
  nohup "$python_bin" -m linux_mcp_agent >>"$LOG_FILE" 2>&1 </dev/null &
  local pid=$!
  printf '%s\n' "$pid" >"$PID_FILE"
  chmod 600 "$PID_FILE" "$LOG_FILE" 2>/dev/null || true

  if ! wait_for_mcp; then
    kill -INT "$pid" 2>/dev/null || true
    printf '\n===== MCP SERVER LOG =====\n' >&2
    tail -n 80 "$LOG_FILE" >&2 || true
    rm -f "$PID_FILE"
    fail "MCP did not become healthy on port $MCP_PORT. See $LOG_FILE."
  fi
  printf 'MCP started (PID %s). Stop it later with bash scripts/stop-demo.sh\n' "$pid"
}

verify_caddy_proxy() {
  local domain="$1"
  mkdir -p "$CONFIG_DIR"
  chmod 700 "$CONFIG_DIR"
  if ! "${compose[@]}" --profile lan exec -T caddy cat /data/caddy/pki/authorities/local/root.crt >"$CA_FILE"; then
    fail "Cannot export the Caddy local root CA from the running container."
  fi
  chmod 644 "$CA_FILE"

  printf 'Checking Caddy HTTPS reverse proxy'
  for _ in $(seq 1 15); do
    if curl --silent --show-error --fail --max-time 3 \
      --cacert "$CA_FILE" \
      --resolve "${domain}:443:127.0.0.1" \
      "https://${domain}/healthz" >/dev/null 2>&1; then
      printf ' healthy\n'
      printf 'Caddy root CA exported to: %s\n' "$CA_FILE"
      return 0
    fi
    printf '.'
    sleep 1
  done

  printf '\n' >&2
  "${compose[@]}" --profile lan logs --tail=80 caddy >&2 || true
  fail "MCP is healthy locally on port $MCP_PORT, but Caddy cannot serve https://$domain/healthz. Check MCP_UPSTREAM and the Caddy logs."
}

command -v docker >/dev/null 2>&1 || fail "Docker is not installed."
command -v curl >/dev/null 2>&1 || fail "curl is required."
[[ -r "$COMPOSE_ENV_FILE" ]] ||
  fail "Missing $COMPOSE_ENV_FILE. Copy deploy/compose/.env.example to deploy/compose/.env and set its secrets."

# The systemd unit uses /etc/linux-mcp-agent/server.env. Read only its port here;
# systemd itself remains responsible for loading the service's full environment.
if command -v systemctl >/dev/null 2>&1 && systemctl cat linux-mcp-agent.service >/dev/null 2>&1; then
  SYSTEMD_MANAGED=true
  SYSTEMD_PORT="$(read_config_value "$SYSTEMD_ENV_FILE" MCP_PORT || true)"
  MCP_PORT="${MCP_PORT_OVERRIDE:-${SYSTEMD_PORT:-3002}}"
else
  if [[ -z "$SERVER_ENV_FILE" ]]; then
    for candidate in "$HOME/.config/linux-mcp-agent/server.env" "/etc/linux-mcp-agent/server.env"; do
      if [[ -r "$candidate" ]]; then
        SERVER_ENV_FILE="$candidate"
        break
      fi
    done
  fi
  if [[ -n "$SERVER_ENV_FILE" && -r "$SERVER_ENV_FILE" ]]; then
    # This is an operator-managed environment file, not repository content.
    set -a
    # shellcheck disable=SC1090
    source "$SERVER_ENV_FILE"
    set +a
  fi
  MCP_PORT="${MCP_PORT_OVERRIDE:-${MCP_PORT:-3002}}"
fi

[[ "$MCP_PORT" =~ ^[0-9]+$ ]] && (( MCP_PORT >= 1 && MCP_PORT <= 65535 )) ||
  fail "MCP_PORT must be an integer between 1 and 65535."

MCP_DOMAIN="${MCP_DOMAIN:-$(compose_env_value MCP_DOMAIN mcp.home.arpa)}"
compose=(docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE")
cd "$ROOT"

printf '== 1/3 Start PostgreSQL and Keycloak ==\n'
"${compose[@]}" config --quiet
"${compose[@]}" up -d postgres keycloak
wait_for_keycloak

printf '\n== Configure browser Keycloak login ==\n'
bash "$ROOT/scripts/configure-browser-client.sh"

printf '\n== 2/3 Ensure MCP is healthy ==\n'
ensure_mcp_running

printf '\n== 3/3 Start Caddy with matching MCP upstream ==\n'
MCP_UPSTREAM="127.0.0.1:$MCP_PORT" "${compose[@]}" --profile lan up -d caddy
verify_caddy_proxy "$MCP_DOMAIN"

printf '\nDemo endpoints:\n'
printf '  Dashboard:  https://%s/dashboard\n' "$MCP_DOMAIN"
printf '  Assistant:  https://%s/assistant\n' "$MCP_DOMAIN"
printf '  MCP:        https://%s/mcp\n' "$MCP_DOMAIN"
printf '  Health:     https://%s/healthz\n' "$MCP_DOMAIN"
if [[ -f "$PID_FILE" ]]; then
  printf '\nMCP was started in demo mode. Stop it with: bash scripts/stop-demo.sh\n'
fi
