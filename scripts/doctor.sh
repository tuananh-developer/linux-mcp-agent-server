#!/usr/bin/env bash
set -Eeuo pipefail

CONFIG_DIR="/etc/linux-mcp-agent"
INSTALL_DIR="/opt/linux-mcp-agent-server"
COMPOSE_FILE="$INSTALL_DIR/deploy/compose/compose.yaml"
COMPOSE_ENV="$CONFIG_DIR/compose.env"

if [[ "$EUID" -ne 0 ]]; then
  command -v sudo >/dev/null 2>&1 || { echo "sudo is required." >&2; exit 1; }
  exec sudo -E bash "$0" "$@"
fi

[[ -f "$CONFIG_DIR/install.conf" ]] || {
  echo "No Linux Observatory managed installation was found."
  exit 1
}
# shellcheck disable=SC1091
source "$CONFIG_DIR/install.conf"

failed=0
check() {
  local label="$1"
  shift
  if "$@"; then
    printf '[PASS] %s\n' "$label"
  else
    printf '[FAIL] %s\n' "$label"
    failed=1
  fi
}

echo "Linux Observatory health report"
echo "Dashboard: https://$MCP_DOMAIN/dashboard"
echo "Auth:      https://$AUTH_DOMAIN"
echo

check "Docker daemon" systemctl is-active --quiet docker
check "MCP systemd service" systemctl is-active --quiet linux-mcp-agent.service
check "MCP loopback health" curl --silent --show-error --fail --max-time 4 http://127.0.0.1:3002/healthz
check "Caddy HTTPS health" curl --silent --show-error --fail --max-time 5 \
  --cacert "$CONFIG_DIR/caddy-root.crt" --resolve "$MCP_DOMAIN:443:127.0.0.1" \
  "https://$MCP_DOMAIN/healthz"
check "Keycloak OIDC discovery" curl --silent --show-error --fail --max-time 5 \
  --cacert "$CONFIG_DIR/caddy-root.crt" --resolve "$AUTH_DOMAIN:443:127.0.0.1" \
  "https://$AUTH_DOMAIN/realms/linux-agent/.well-known/openid-configuration"
check "Encrypted vault master key" test -s "$CONFIG_DIR/provider-vault.key"
check "Encrypted vault store directory" test -d /var/lib/linux-mcp-agent

echo
docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" --profile lan ps
echo
if (( failed != 0 )); then
  echo "One or more checks failed. Recent MCP logs:"
  journalctl -u linux-mcp-agent.service -n 50 --no-pager
  exit 1
fi
echo "All local health checks passed."
echo "For another LAN device, verify DNS maps both hostnames to $LAN_IP and install the Caddy root CA."
