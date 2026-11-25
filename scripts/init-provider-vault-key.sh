#!/usr/bin/env bash
set -Eeuo pipefail

KEY_DIR="/etc/linux-mcp-agent"
KEY_FILE="$KEY_DIR/provider-vault.key"
STATE_DIR="/var/lib/linux-mcp-agent"
SERVICE_USER="linux-mcp-agent"

if [[ "$EUID" -ne 0 ]]; then
  exec sudo -E bash "$0" "$@"
fi

id "$SERVICE_USER" >/dev/null 2>&1 || {
  printf 'ERROR: service account %s does not exist. Create it using deploy/systemd/README.md first.\n' "$SERVICE_USER" >&2
  exit 1
}

install -d -o root -g "$SERVICE_USER" -m 0750 "$KEY_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0700 "$STATE_DIR"

if [[ -e "$KEY_FILE" ]]; then
  [[ -f "$KEY_FILE" && ! -L "$KEY_FILE" ]] || {
    printf 'ERROR: %s must be a regular, non-symlink file.\n' "$KEY_FILE" >&2
    exit 1
  }
  [[ "$(stat -c '%s' "$KEY_FILE")" == "32" ]] || {
    printf 'ERROR: existing provider vault key must contain exactly 32 bytes.\n' >&2
    exit 1
  }
  chown root:root "$KEY_FILE"
  chmod 0600 "$KEY_FILE"
  printf 'Provider vault key already exists; leaving its contents unchanged.\n'
else
  temporary_file="$(mktemp)"
  trap 'rm -f "$temporary_file"' EXIT
  python3 -c 'import secrets,sys; sys.stdout.buffer.write(secrets.token_bytes(32))' >"$temporary_file"
  install -o root -g root -m 0600 "$temporary_file" "$KEY_FILE"
  rm -f "$temporary_file"
  trap - EXIT
  printf 'Generated a new 256-bit provider vault key.\n'
fi

printf 'Key source: %s\n' "$KEY_FILE"
printf 'systemd will expose it to the service as a private credential.\n'
printf 'Encrypted credential store: %s/provider-credentials.json\n' "$STATE_DIR"
printf 'Do not delete or regenerate the key while the vault contains credentials.\n'
