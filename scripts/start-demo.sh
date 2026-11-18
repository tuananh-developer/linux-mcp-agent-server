#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$ROOT/deploy/compose"
COMPOSE_FILE="$COMPOSE_DIR/compose.yaml"
COMPOSE_ENV_FILE="\${LINUX_MCP_COMPOSE_ENV_FILE:-$COMPOSE_DIR/.env}"
MCP_PORT="\${MCP_PORT:-3002}"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

wait_for_keycloak() {
  local container_id status
  container_id="$("\${compose[@]}" ps -q keycloak)"
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
        "\${compose[@]}" logs --tail=60 keycloak >&2
        fail "Keycloak is $status. Check the logs above."
        ;;
    esac
    printf '.'
    sleep 2
  done
  printf '\n'
  "\${compose[@]}" logs --tail=60 keycloak >&2
  fail "Timed out waiting for Keycloak to become healthy."
}

wait_for_mcp() {
  local url="http://127.0.0.1:\${MCP_PORT}/healthz"
  printf 'Waiting for MCP health check'
  for _ in $(seq 1 30); do
    if curl --silent --show-error --fail "$url" >/dev/null 2>&1; then
      printf ' ready\n'
      return 0
    fi
    printf '.'
    sleep 1
  done
  printf '\n'
  return 1
}

command -v docker >/dev/null 2>&1 || fail "Docker is not installed."
command -v curl >/dev/null 2>&1 || fail "curl is required."
[[ -r "$COMPOSE_ENV_FILE" ]] || fail "Missing $COMPOSE_ENV_FILE. Copy deploy/compose/.env.example to deploy/compose/.env and set its secrets."

compose=(docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE")
cd "$ROOT"

printf '== 1/3 Start PostgreSQL and Keycloak ==\n'
"\${compose[@]}" config --quiet
"\${compose[@]}" up -d postgres keycloak
wait_for_keycloak

printf '\n== 2/3 Start Caddy HTTPS ingress ==\n'
"\${compose[@]}" --profile lan up -d caddy

printf '\n== 3/3 Ensure the MCP application is running ==\n'
if wait_for_mcp; then
  printf 'MCP is already healthy at http://127.0.0.1:%s/healthz\n' "$MCP_PORT"
  printf 'Demo endpoint: https://mcp.home.arpa/mcp\n'
  exit 0
fi

if command -v systemctl >/dev/null 2>&1 && systemctl cat linux-mcp-agent.service >/dev/null 2>&1; then
  printf 'Starting the installed systemd service...\n'
  sudo systemctl restart linux-mcp-agent.service
  wait_for_mcp || {
    sudo systemctl status --no-pager linux-mcp-agent.service >&2 || true
    fail "MCP did not become healthy after the systemd restart."
  }
  printf 'MCP systemd service is healthy.\n'
  exit 0
fi

SERVER_ENV_FILE="\${LINUX_MCP_SERVER_ENV_FILE:-}"
if [[ -z "$SERVER_ENV_FILE" ]]; then
  for candidate in "$HOME/.config/linux-mcp-agent/server.env" "/etc/linux-mcp-agent/server.env"; do
    if [[ -r "$candidate" ]]; then
      SERVER_ENV_FILE="$candidate"
      break
    fi
  done
fi

if [[ -z "$SERVER_ENV_FILE" || ! -r "$SERVER_ENV_FILE" ]]; then
  fail "MCP is not running and no readable server.env was found. Install the systemd service (deploy/systemd/README.md), or create ~/.config/linux-mcp-agent/server.env from deploy/systemd/server.env.example and set LINUX_MCP_SERVER_ENV_FILE if needed."
fi

printf 'Launching MCP in the foreground using %s\n' "$SERVER_ENV_FILE"
printf 'Press Ctrl+C to stop the MCP process after the demo.\n'
# This is a trusted, operator-managed KEY=VALUE file; it is not repository content.
set -a
# shellcheck disable=SC1090
source "$SERVER_ENV_FILE"
set +a

[[ "\${AUTH_MODE:-}" == "keycloak" ]] || fail "Server environment must set AUTH_MODE=keycloak."
MCP_PORT="\${MCP_PORT:-3002}"
if [[ ! -f "\${LOG_SOURCES_FILE:-}" && -f "$ROOT/config/log-sources.example.json" ]]; then
  export LOG_SOURCES_FILE="$ROOT/config/log-sources.example.json"
fi

command -v uv >/dev/null 2>&1 || fail "uv is required to launch the MCP server."
exec uv run linux-mcp-agent
