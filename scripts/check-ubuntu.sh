#!/usr/bin/env bash
set -euo pipefail

ok() { printf 'OK   %s\n' "$1"; }
miss() { printf 'MISS %s\n' "$1" >&2; }
failed=0

if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  if [[ "${ID:-}" == ubuntu && "${VERSION_ID:-}" == "24.04" ]]; then ok "Ubuntu ${VERSION_ID}"; else miss "Expected Ubuntu 24.04 LTS (found ${PRETTY_NAME:-unknown})"; failed=1; fi
else
  miss '/etc/os-release is unavailable'; failed=1
fi

if command -v uv >/dev/null 2>&1; then
  uv_version="$(uv --version | awk '{print $2}')"
  if [[ "$uv_version" == "0.13.6" ]]; then ok "uv ${uv_version}"; else miss "uv ${uv_version}; expected 0.13.6"; failed=1; fi
else
  miss 'uv 0.13.6 is not installed'; failed=1
fi

if command -v journalctl >/dev/null 2>&1; then ok "journalctl $(command -v journalctl)"; else miss 'journalctl is not installed'; failed=1; fi
if command -v docker >/dev/null 2>&1; then ok "Docker $(docker --version)"; else miss 'Docker is not installed (needed only for Keycloak/Caddy/PostgreSQL)'; fi

if [[ -f .python-version ]]; then
  wanted="$(tr -d '[:space:]' < .python-version)"
  actual="$(python --version 2>&1 | awk '{print $2}')"
  if [[ "$actual" == "$wanted" ]]; then ok "Python ${actual}"; else miss "Python ${actual:-not found}; project pin is ${wanted}. Use 'uv python install ${wanted}' and 'uv run'"; failed=1; fi
else
  miss '.python-version is missing'; failed=1
fi

exit "$failed"
