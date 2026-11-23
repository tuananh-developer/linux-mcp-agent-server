#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_ENV_FILE="${LINUX_MCP_COMPOSE_ENV_FILE:-$ROOT/deploy/compose/.env}"
COMPOSE_FILE="$ROOT/deploy/compose/compose.yaml"
OUTPUT="${1:-$HOME/.config/linux-mcp-agent/caddy-root.crt}"

command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker is not installed." >&2; exit 1; }
[[ -r "$COMPOSE_ENV_FILE" ]] || { echo "ERROR: Missing $COMPOSE_ENV_FILE." >&2; exit 1; }

mkdir -p "$(dirname "$OUTPUT")"
docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" --profile lan \
  exec -T caddy cat /data/caddy/pki/authorities/local/root.crt > "$OUTPUT"
chmod 644 "$OUTPUT"
openssl x509 -in "$OUTPUT" -noout -subject -issuer -dates
printf 'Caddy root CA exported to: %s\n' "$OUTPUT"
