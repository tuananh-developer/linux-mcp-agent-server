#!/usr/bin/env bash
set -Eeuo pipefail

CA_FILE="${1:-$HOME/.config/linux-mcp-agent/caddy-root.crt}"
[[ -r "$CA_FILE" ]] || { echo "ERROR: Cannot read CA certificate: $CA_FILE" >&2; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "ERROR: openssl is required." >&2; exit 1; }
openssl x509 -in "$CA_FILE" -noout >/dev/null || { echo "ERROR: Invalid PEM certificate." >&2; exit 1; }

if command -v update-ca-trust >/dev/null 2>&1; then
  target="/etc/pki/ca-trust/source/anchors/linux-mcp-agent-caddy-root.crt"
  sudo install -D -m 0644 "$CA_FILE" "$target"
  sudo update-ca-trust extract
elif command -v update-ca-certificates >/dev/null 2>&1; then
  target="/usr/local/share/ca-certificates/linux-mcp-agent-caddy-root.crt"
  sudo install -D -m 0644 "$CA_FILE" "$target"
  sudo update-ca-certificates
else
  echo "ERROR: Neither update-ca-trust nor update-ca-certificates is available." >&2
  exit 1
fi

printf 'Caddy root CA installed in the operating-system trust store. Restart the browser before opening the dashboard.\n'
