#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="/opt/linux-mcp-agent-server"
CONFIG_DIR="/etc/linux-mcp-agent"
COMPOSE_FILE="$INSTALL_DIR/deploy/compose/compose.yaml"
COMPOSE_ENV="$CONFIG_DIR/compose.env"
PYTHON_VERSION="3.15.2"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
if [[ "$EUID" -ne 0 ]]; then
  command -v sudo >/dev/null 2>&1 || die "sudo is required."
  sudo -v
  exec sudo -E bash "$0" "$@"
fi

ROOT="$(pwd -P)"
[[ -f "$ROOT/pyproject.toml" && -f "$ROOT/scripts/upgrade.sh" ]] ||
  die "Run from the root of a fresh repository clone."
[[ -f "$CONFIG_DIR/install.conf" ]] || die "No managed installation found at $CONFIG_DIR."
[[ -f "$CONFIG_DIR/server.env" && -f "$CONFIG_DIR/compose.env" ]] ||
  die "Installation config is incomplete; refusing to change the running system."
[[ -d "$INSTALL_DIR" && -f "$INSTALL_DIR/.venv/bin/python" ]] ||
  die "Installed application or virtual environment is missing."

# shellcheck disable=SC1091
source "$CONFIG_DIR/install.conf"
[[ "$INSTALL_DIR" == "/opt/linux-mcp-agent-server" ]] || die "Unexpected installation directory."
[[ -f "$CONFIG_DIR/provider-vault.key" && -f "$CONFIG_DIR/log-sources.json" ]] ||
  die "Provider vault key or log-source configuration is missing."

echo "Stopping MCP service before replacing application files..."
systemctl stop linux-mcp-agent.service

rsync -a --delete \
  --exclude='/.git/' --exclude='/.venv/' --exclude='/.uv-python/' --exclude='/uv.lock' \
  --exclude='/.pytest_cache/' --exclude='/.ruff_cache/' \
  --exclude='/.env' --exclude='/deploy/compose/.env' --exclude='__pycache__/' \
  "$ROOT/" "$INSTALL_DIR/"
chown -R root:root "$INSTALL_DIR"

export UV_PYTHON_INSTALL_DIR="$INSTALL_DIR/.uv-python"
export UV_CACHE_DIR="/var/cache/linux-mcp-agent/uv"
UV_BIN="$(command -v uv || true)"
[[ -x "$UV_BIN" ]] || UV_BIN="/usr/local/bin/uv"
if ! "$UV_BIN" sync --project "$INSTALL_DIR" --python "$PYTHON_VERSION" --no-dev; then
  echo "Dependency synchronization failed; attempting to bring the service back." >&2
  systemctl start linux-mcp-agent.service || true
  exit 1
fi

install -o root -g root -m 0644 "$INSTALL_DIR/deploy/systemd/linux-mcp-agent.service" \
  /etc/systemd/system/linux-mcp-agent.service
systemctl daemon-reload

docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" config --quiet
docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" up -d postgres keycloak
systemctl restart linux-mcp-agent.service
docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" --profile lan \
  up -d --force-recreate caddy

MCP_READY=false
for _ in $(seq 1 30); do
  if curl --silent --show-error --fail --max-time 2 \
    http://127.0.0.1:3002/healthz >/dev/null 2>&1; then
    MCP_READY=true
    break
  fi
  sleep 1
done
if [[ "$MCP_READY" != "true" ]]; then
  systemctl status linux-mcp-agent.service --no-pager -l >&2 || true
  journalctl -u linux-mcp-agent.service -n 60 --no-pager >&2 || true
  die "MCP health check failed after upgrade."
fi

curl --silent --show-error --fail --max-time 5 \
  --cacert "$CONFIG_DIR/caddy-root.crt" \
  --resolve "$MCP_DOMAIN:443:127.0.0.1" \
  "https://$MCP_DOMAIN/healthz" >/dev/null ||
  die "HTTPS health check failed after upgrade."

echo "Upgrade completed. Existing Keycloak database, account credentials, server settings, vault master key and encrypted provider keys were preserved."
systemctl --no-pager --full status linux-mcp-agent.service | sed -n '1,12p'
