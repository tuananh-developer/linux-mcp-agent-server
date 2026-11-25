#!/usr/bin/env bash
set -Eeuo pipefail

CONFIG_DIR="/etc/linux-mcp-agent"
INSTALL_DIR="/opt/linux-mcp-agent-server"
COMPOSE_FILE="$INSTALL_DIR/deploy/compose/compose.yaml"
COMPOSE_ENV="$CONFIG_DIR/compose.env"
PURGE=false

if [[ "$EUID" -ne 0 ]]; then
  command -v sudo >/dev/null 2>&1 || { echo "sudo is required." >&2; exit 1; }
  exec sudo -E bash "$0" "$@"
fi
if (( $# > 1 )); then echo "Usage: sudo bash scripts/uninstall.sh [--purge-data]" >&2; exit 2; fi
if (( $# == 1 )); then
  [[ "$1" == "--purge-data" ]] || { echo "Unknown option: $1" >&2; exit 2; }
  PURGE=true
fi
[[ -f "$CONFIG_DIR/install.conf" ]] || {
  echo "No Linux Observatory managed installation was found."
  exit 1
}
# shellcheck disable=SC1091
source "$CONFIG_DIR/install.conf"

echo "This will stop Linux Observatory and remove its application and systemd unit."
if [[ "$PURGE" == "true" ]]; then
  echo "PURGE MODE: Keycloak database volume, vault ciphertext, master key and configuration will be permanently deleted."
fi
read -r -p "Type UNINSTALL to continue: " confirmation
[[ "$confirmation" == "UNINSTALL" ]] || { echo "Cancelled."; exit 0; }
if [[ "$PURGE" == "true" ]]; then
  read -r -p "Type DELETE DATA to permanently delete stored data: " purge_confirmation
  [[ "$purge_confirmation" == "DELETE DATA" ]] || { echo "Cancelled."; exit 0; }
fi

systemctl disable --now linux-mcp-agent.service 2>/dev/null || true
if [[ -f "$COMPOSE_FILE" && -f "$COMPOSE_ENV" ]]; then
  if [[ "$PURGE" == "true" ]]; then
    docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" --profile lan down --volumes --remove-orphans || true
  else
    docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" --profile lan down --remove-orphans || true
  fi
fi

rm -f /etc/systemd/system/linux-mcp-agent.service
systemctl daemon-reload
rm -rf "$INSTALL_DIR"

HOSTS_TEMP="$(mktemp)"
awk '
  $0 == "# BEGIN LINUX OBSERVATORY MANAGED HOSTS" { skip=1; next }
  $0 == "# END LINUX OBSERVATORY MANAGED HOSTS" { skip=0; next }
  !skip { print }
' /etc/hosts > "$HOSTS_TEMP"
install -o root -g root -m 0644 "$HOSTS_TEMP" /etc/hosts
rm -f "$HOSTS_TEMP"

rm -f /usr/local/share/ca-certificates/linux-observatory-root.crt
update-ca-certificates >/dev/null || true

if [[ "$PURGE" == "true" ]]; then
  rm -rf "$CONFIG_DIR" /var/lib/linux-mcp-agent /var/cache/linux-mcp-agent
  echo "Application, configuration, vault and Compose volumes removed."
else
  echo "Application and service removed. Configuration, vault keys, encrypted credentials and Compose database volumes were retained in:"
  echo "  $CONFIG_DIR"
  echo "  /var/lib/linux-mcp-agent"
  echo "These retained files are sensitive; back them up or run --purge-data if you intend permanent deletion."
fi
echo "Docker Engine and uv were left installed because other applications may use them."
