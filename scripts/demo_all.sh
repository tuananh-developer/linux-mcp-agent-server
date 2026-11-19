#!/usr/bin/env bash
# Full repository demo: infrastructure, MCP live calls, security smoke tests and quality checks.
# This script does not install packages, change Keycloak secrets, or edit env files.

set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_ENV="$ROOT/deploy/compose/.env"
COMPOSE_FILE="$ROOT/deploy/compose/compose.yaml"
SERVER_ENV="$HOME/.config/linux-mcp-agent/server.env"
CLIENT_ENV="$HOME/.config/linux-mcp-agent/keycloak-clients.env"
MCP_PORT="3002"
MCP_ENDPOINT="https://mcp.home.arpa/mcp"
MCP_HEALTH_URL="http://127.0.0.1:$MCP_PORT/healthz"
DEMO_LOG="$HOME/mcp-live-demo-$(date +%Y%m%d-%H%M%S).log"

USE_INSECURE=0
CA_CERT=""
SKIP_QUALITY=0
OVERALL_FAILURES=0
LIVE_RESULT="NOT RUN"
RUFF_RESULT="NOT RUN"
PYRIGHT_RESULT="NOT RUN"
PYTEST_RESULT="NOT RUN"

usage() {
  cat <<'EOF'
Usage: bash scripts/demo_all.sh [options]

Options:
  --insecure          Disable TLS verification for this isolated local demo VM.
  --ca-cert PATH      Verify Caddy TLS with the supplied local root CA PEM.
  --skip-quality      Skip Ruff, Pyright and pytest.
  -h, --help          Show this help.

Examples:
  bash scripts/demo_all.sh --insecure
  bash scripts/demo_all.sh --ca-cert ./caddy-local-root.crt
EOF
}

fail() {
  printf '\nERROR: %s\n' "$1" >&2
  exit 1
}

pass() {
  printf 'PASS: %s\n' "$1"
}

section() {
  printf '\n============================================================\n'
  printf '%s\n' "$1"
  printf '============================================================\n'
}

has_nonempty_setting() {
  key="$1"
  file="$2"
  grep -Eq "^[[:space:]]*$key[[:space:]]*=[[:space:]]*[^[:space:]#]" "$file"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --insecure)
      USE_INSECURE=1
      shift
      ;;
    --ca-cert)
      [[ $# -ge 2 ]] || fail "--ca-cert requires a PEM path."
      CA_CERT="$2"
      shift 2
      ;;
    --skip-quality)
      SKIP_QUALITY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1 (use --help)."
      ;;
  esac
done

[[ "$USE_INSECURE" -eq 0 || -z "$CA_CERT" ]] || fail "Choose either --insecure or --ca-cert, not both."
[[ -z "$CA_CERT" || -r "$CA_CERT" ]] || fail "Cannot read CA certificate: $CA_CERT"

curl_tls() {
  if [[ "$USE_INSECURE" -eq 1 ]]; then
    curl --insecure "$@"
  elif [[ -n "$CA_CERT" ]]; then
    curl --cacert "$CA_CERT" "$@"
  else
    curl "$@"
  fi
}

section "0/6 — Preflight configuration"
for command_name in docker curl uv python3 grep; do
  command -v "$command_name" >/dev/null 2>&1 || fail "Required command not found: $command_name"
done
[[ -r "$COMPOSE_ENV" ]] || fail "Missing $COMPOSE_ENV. Prepare it using docs/10_live_demo.md."
[[ -r "$SERVER_ENV" ]] || fail "Missing $SERVER_ENV. Prepare it using docs/10_live_demo.md."
[[ -r "$CLIENT_ENV" ]] || fail "Missing $CLIENT_ENV. It must contain the MCP Agent client credentials."

has_nonempty_setting "AUTH_MODE" "$SERVER_ENV" || fail "server.env is missing AUTH_MODE."
grep -Eq '^[[:space:]]*AUTH_MODE[[:space:]]*=[[:space:]]*keycloak[[:space:]]*$' "$SERVER_ENV" \
  || fail "server.env must set AUTH_MODE=keycloak."
has_nonempty_setting "MCP_INTROSPECTION_CLIENT_ID" "$SERVER_ENV" \
  || fail "server.env is missing MCP_INTROSPECTION_CLIENT_ID."
has_nonempty_setting "MCP_INTROSPECTION_CLIENT_SECRET" "$SERVER_ENV" \
  || fail "server.env is missing MCP_INTROSPECTION_CLIENT_SECRET."
has_nonempty_setting "MCP_AGENT_CLIENT_ID" "$CLIENT_ENV" \
  || fail "keycloak-clients.env is missing MCP_AGENT_CLIENT_ID."
has_nonempty_setting "MCP_AGENT_CLIENT_SECRET" "$CLIENT_ENV" \
  || fail "keycloak-clients.env is missing MCP_AGENT_CLIENT_SECRET."
grep -Eq '^[[:space:]]*MCP_PORT[[:space:]]*=[[:space:]]*3002[[:space:]]*$' "$SERVER_ENV" \
  || fail "This Caddy configuration expects MCP_PORT=3002."
[[ -f "$ROOT/config/log-sources.example.json" ]] || fail "Missing log source allowlist."

chmod 600 "$SERVER_ENV" "$CLIENT_ENV" "$COMPOSE_ENV"
docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" config --quiet
pass "Required commands and local configuration are present (secret values were not displayed)."
pass "Docker Compose configuration is valid."

if [[ "$USE_INSECURE" -eq 1 ]]; then
  printf 'TLS mode: INSECURE (only use on this isolated demo VM).\n'
elif [[ -n "$CA_CERT" ]]; then
  printf 'TLS mode: custom trusted CA (%s).\n' "$CA_CERT"
else
  printf 'TLS mode: system trust store (certificate verification enabled).\n'
fi

section "1/6 — Start infrastructure and MCP Server"
printf 'Starting PostgreSQL, Keycloak, Caddy and ensuring MCP is running...\n'
# Wait until start-demo.sh has completed its infrastructure checks. If it has to
# launch Uvicorn in the foreground, detect that mode and keep the server alive.
STARTUP_LOG="$HOME/mcp-demo-startup-$(date +%Y%m%d-%H%M%S).log"
: > "$STARTUP_LOG"
bash "$ROOT/scripts/start-demo.sh" > "$STARTUP_LOG" 2>&1 &
START_DEMO_PID=$!
STARTUP_MODE=""
STARTUP_WAITED=0

for ((attempt = 1; attempt <= 240; attempt++)); do
  if grep -q "Launching MCP in the foreground" "$STARTUP_LOG"; then
    STARTUP_MODE="foreground"
    break
  fi
  if grep -Eq "MCP is already healthy|MCP systemd service is healthy" "$STARTUP_LOG"; then
    STARTUP_MODE="completed"
    break
  fi
  if ! kill -0 "$START_DEMO_PID" 2>/dev/null; then
    if wait "$START_DEMO_PID"; then
      STARTUP_WAITED=1
      STARTUP_MODE="completed"
      break
    else
      status=$?
      cat "$STARTUP_LOG" >&2
      fail "scripts/start-demo.sh exited with status $status."
    fi
  fi
  if (( attempt % 5 == 0 )); then
    printf '.'
  fi
  sleep 1
done
printf '\n'
[[ -n "$STARTUP_MODE" ]] || {
  cat "$STARTUP_LOG" >&2
  fail "Timed out waiting for scripts/start-demo.sh to finish its startup checks."
}

if [[ "$STARTUP_MODE" == "completed" && "$STARTUP_WAITED" -eq 0 ]]; then
  if wait "$START_DEMO_PID"; then
    STARTUP_WAITED=1
  else
    status=$?
    cat "$STARTUP_LOG" >&2
    fail "scripts/start-demo.sh exited with status $status."
  fi
fi
cat "$STARTUP_LOG"

MCP_READY=0
for ((attempt = 1; attempt <= 60; attempt++)); do
  if curl --silent --show-error --fail --connect-timeout 2 --max-time 3 \
      "$MCP_HEALTH_URL" >/dev/null 2>&1; then
    MCP_READY=1
    break
  fi
  if [[ "$STARTUP_MODE" == "foreground" ]] && ! kill -0 "$START_DEMO_PID" 2>/dev/null; then
    if wait "$START_DEMO_PID"; then
      status=0
    else
      status=$?
    fi
    tail -n 60 "$STARTUP_LOG" >&2
    fail "MCP foreground process exited before becoming healthy (status $status)."
  fi
  sleep 1
done

[[ "$MCP_READY" -eq 1 ]] || {
  tail -n 60 "$STARTUP_LOG" >&2
  fail "MCP did not become healthy within 60 seconds."
}
pass "MCP health endpoint returned HTTP 200 at $MCP_HEALTH_URL"
printf 'Startup log: %s\n' "$STARTUP_LOG"

printf '\nDocker services:\n'
docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" --profile lan ps

section "2/6 — Verify HTTPS, OIDC metadata and authorization boundary"
metadata_status="$(curl_tls --noproxy '*' --silent --show-error \
  --output /dev/null --write-out '%{http_code}' --max-time 10 \
  https://mcp.home.arpa/.well-known/oauth-protected-resource/mcp)" \
  || fail "Cannot reach MCP protected-resource metadata."
[[ "$metadata_status" == "200" ]] || fail "Protected-resource metadata returned HTTP $metadata_status (expected 200)."
pass "Protected-resource metadata is reachable over HTTPS (HTTP 200)."

oidc_status="$(curl_tls --noproxy '*' --silent --show-error \
  --output /dev/null --write-out '%{http_code}' --max-time 10 \
  https://auth.home.arpa/realms/linux-agent/.well-known/openid-configuration)" \
  || fail "Cannot reach Keycloak OIDC discovery."
[[ "$oidc_status" == "200" ]] || fail "Keycloak OIDC discovery returned HTTP $oidc_status (expected 200)."
pass "Keycloak OIDC discovery is reachable over HTTPS (HTTP 200)."

unauth_status="$(curl_tls --noproxy '*' --silent --show-error \
  --output /dev/null --write-out '%{http_code}' --max-time 10 \
  --request POST \
  --header 'Content-Type: application/json' \
  --header 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":9001,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"unauthenticated-smoke-test","version":"1.0.0"}}}' \
  "$MCP_ENDPOINT")" || fail "Could not complete unauthenticated MCP boundary check."
[[ "$unauth_status" == "401" ]] || fail "Unauthenticated MCP request returned HTTP $unauth_status (expected 401)."
pass "MCP rejects a request without a Bearer token (HTTP 401)."

public_health_status="$(curl_tls --noproxy '*' --silent --show-error \
  --output /dev/null --write-out '%{http_code}' --max-time 10 \
  https://mcp.home.arpa/healthz)" || fail "Could not check the public health route."
[[ "$public_health_status" == "404" ]] || fail "Caddy exposed /healthz unexpectedly (HTTP $public_health_status; expected 404)."
pass "Caddy does not expose backend /healthz through the MCP hostname (HTTP 404)."

section "3/6 — Live authenticated MCP demo: all server capabilities"
printf 'The client output is also saved to: %s\n' "$DEMO_LOG"
if [[ "$USE_INSECURE" -eq 1 ]]; then
  if uv run python scripts/demo_live.py --insecure 2>&1 | tee "$DEMO_LOG"; then
    LIVE_RESULT="PASS"
    pass "Live MCP acceptance client completed successfully."
  else
    LIVE_RESULT="FAIL"
    OVERALL_FAILURES=$((OVERALL_FAILURES + 1))
    printf 'FAIL: Review the output above and %s.\n' "$DEMO_LOG" >&2
  fi
elif [[ -n "$CA_CERT" ]]; then
  if uv run python scripts/demo_live.py --ca-cert "$CA_CERT" 2>&1 | tee "$DEMO_LOG"; then
    LIVE_RESULT="PASS"
    pass "Live MCP acceptance client completed successfully."
  else
    LIVE_RESULT="FAIL"
    OVERALL_FAILURES=$((OVERALL_FAILURES + 1))
    printf 'FAIL: Review the output above and %s.\n' "$DEMO_LOG" >&2
  fi
else
  if uv run python scripts/demo_live.py 2>&1 | tee "$DEMO_LOG"; then
    LIVE_RESULT="PASS"
    pass "Live MCP acceptance client completed successfully."
  else
    LIVE_RESULT="FAIL"
    OVERALL_FAILURES=$((OVERALL_FAILURES + 1))
    printf 'FAIL: Review the output above and %s.\n' "$DEMO_LOG" >&2
  fi
fi

section "4/6 — Repository implementation inventory"
cat <<'EOF'
MCP server modules:
  server.py       — 8 Tools, 1 Resource, 1 Prompt, ASGI composition
  system.py       — CPU, memory, disk and process telemetry
  diagnostics.py  — network, service, local-port and threshold diagnostics
  log_reader.py   — allowlisted, bounded and redacted journald reader
  auth.py         — Keycloak RFC 7662 token introspection
  auth_claims.py  — issuer, expiry, audience, scope and client validation
  config.py       — environment parsing and security validation
  __main__.py     — Uvicorn application entry point

Deployment assets:
  deploy/compose/ — PostgreSQL, Keycloak and Caddy infrastructure
  deploy/caddy/   — HTTPS reverse proxy and route allowlist
  deploy/keycloak/— Realm and confidential-client template
  deploy/systemd/ — hardened native Linux service template

Operational scripts:
  scripts/check-ubuntu.sh — host prerequisite check
  scripts/setup-linux.sh  — optional installation and environment setup
  scripts/start-demo.sh  — infrastructure and MCP startup
  scripts/demo_live.py   — live OAuth + MCP client acceptance
EOF
if [[ -f "$ROOT/deploy/systemd/linux-mcp-agent.service" ]]; then
  pass "Hardened systemd deployment unit template is present (not installed or modified by this demo)."
fi
printf 'LLM/AI Agent inference is outside this repository; an external Agent/MCP Client supplies it.\n'

section "5/6 — Static analysis and automated tests"
run_quality_check() {
  label="$1"
  shift
  printf '\n--- %s ---\n' "$label"
  if "$@"; then
    printf 'PASS: %s\n' "$label"
    return 0
  else
    printf 'FAIL: %s\n' "$label" >&2
    OVERALL_FAILURES=$((OVERALL_FAILURES + 1))
    return 1
  fi
}

if [[ "$SKIP_QUALITY" -eq 1 ]]; then
  printf 'Quality checks skipped by --skip-quality.\n'
else
  if run_quality_check "Ruff" uv run ruff check .; then RUFF_RESULT="PASS"; else RUFF_RESULT="FAIL"; fi
  if run_quality_check "Pyright" uv run pyright; then PYRIGHT_RESULT="PASS"; else PYRIGHT_RESULT="FAIL"; fi
  if run_quality_check "Pytest" uv run pytest; then PYTEST_RESULT="PASS"; else PYTEST_RESULT="FAIL"; fi
fi

section "6/6 — Demo summary"
printf 'Infrastructure / MCP health : PASS\n'
printf 'HTTPS / OIDC / auth boundary: PASS\n'
printf 'Live MCP acceptance         : %s\n' "$LIVE_RESULT"
printf 'Ruff                        : %s\n' "$RUFF_RESULT"
printf 'Pyright                     : %s\n' "$PYRIGHT_RESULT"
printf 'Pytest                      : %s\n' "$PYTEST_RESULT"
printf 'Live demo transcript        : %s\n' "$DEMO_LOG"

if [[ "$OVERALL_FAILURES" -eq 0 && "$LIVE_RESULT" == "PASS" ]]; then
  printf '\n============================================\n'
  printf 'FULL REPOSITORY DEMO: PASS\n'
  printf '============================================\n'
  exit 0
fi

printf '\n============================================\n'
printf 'FULL REPOSITORY DEMO: FAILED (%s failed stage(s))\n' "$OVERALL_FAILURES"
printf '============================================\n'
exit 1
