#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_ENV_FILE="$(printenv LINUX_MCP_COMPOSE_ENV_FILE || true)"
[[ -n "$COMPOSE_ENV_FILE" ]] || COMPOSE_ENV_FILE="$ROOT/deploy/compose/.env"
COMPOSE_FILE="$ROOT/deploy/compose/compose.yaml"

[[ -r "$COMPOSE_ENV_FILE" ]] || {
  echo "ERROR: Missing Compose env file: $COMPOSE_ENV_FILE" >&2
  exit 1
}
command -v docker >/dev/null 2>&1 || {
  echo "ERROR: Docker is required." >&2
  exit 1
}

docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" exec -T keycloak /bin/bash -s <<'IN_CONTAINER'
set -Eeuo pipefail

KCADM=/opt/keycloak/bin/kcadm.sh
REALM=linux-agent
CLIENT_ID=linux-observatory-browser
ORIGIN=https://mcp.home.arpa
ADMIN_USER="$(printenv KC_BOOTSTRAP_ADMIN_USERNAME || true)"
ADMIN_PASSWORD="$(printenv KC_BOOTSTRAP_ADMIN_PASSWORD || true)"

[[ -n "$ADMIN_USER" && -n "$ADMIN_PASSWORD" ]] || {
  echo "ERROR: Keycloak bootstrap admin credentials are unavailable in the container." >&2
  exit 1
}

"$KCADM" config credentials \
  --server http://127.0.0.1:8080 \
  --realm master \
  --user "$ADMIN_USER" \
  --password "$ADMIN_PASSWORD" >/dev/null

CLIENT_UUID="$("$KCADM" get clients -r "$REALM" -q "clientId=$CLIENT_ID" --fields id --format csv --noquotes | tail -n 1 | tr -d '\r')"

if [[ -z "$CLIENT_UUID" ]]; then
  "$KCADM" create clients -r "$REALM" \
    -s "clientId=$CLIENT_ID" \
    -s "name=Linux Observatory Browser (PKCE)" \
    -s enabled=true \
    -s publicClient=true \
    -s serviceAccountsEnabled=false \
    -s standardFlowEnabled=true \
    -s implicitFlowEnabled=false \
    -s directAccessGrantsEnabled=false \
    -s protocol=openid-connect \
    -s "redirectUris=[\"$ORIGIN/*\"]" \
    -s "webOrigins=[\"$ORIGIN\"]" \
    -s 'attributes."pkce.code.challenge.method"=S256'
  CLIENT_UUID="$("$KCADM" get clients -r "$REALM" -q "clientId=$CLIENT_ID" --fields id --format csv --noquotes | tail -n 1 | tr -d '\r')"
fi

[[ -n "$CLIENT_UUID" ]] || {
  echo "ERROR: Could not create or locate the browser OAuth client." >&2
  exit 1
}

"$KCADM" update "clients/$CLIENT_UUID" -r "$REALM" \
  -s enabled=true \
  -s publicClient=true \
  -s serviceAccountsEnabled=false \
  -s standardFlowEnabled=true \
  -s implicitFlowEnabled=false \
  -s directAccessGrantsEnabled=false \
  -s protocol=openid-connect \
  -s "redirectUris=[\"$ORIGIN/*\"]" \
  -s "webOrigins=[\"$ORIGIN\"]" \
  -s 'attributes."pkce.code.challenge.method"=S256' >/dev/null

for SCOPE_NAME in mcp.read mcp.logs.read; do
  SCOPE_ID="$("$KCADM" get client-scopes -r "$REALM" -q "name=$SCOPE_NAME" --fields id --format csv --noquotes | tail -n 1 | tr -d '\r')"
  [[ -n "$SCOPE_ID" ]] || {
    echo "ERROR: Required Keycloak client scope '$SCOPE_NAME' is missing from realm '$REALM'." >&2
    exit 1
  }

  if [[ "$SCOPE_NAME" == "mcp.read" ]]; then
    RELATION=default-client-scopes
  else
    RELATION=optional-client-scopes
  fi
  if ! "$KCADM" get "clients/$CLIENT_UUID/$RELATION" -r "$REALM" | grep -Fq "$SCOPE_NAME"; then
    "$KCADM" update "clients/$CLIENT_UUID/$RELATION/$SCOPE_ID" -r "$REALM" >/dev/null
  fi
done

MAPPERS="$("$KCADM" get "clients/$CLIENT_UUID/protocol-mappers/models" -r "$REALM")"
if ! grep -Fq 'mcp-resource-audience' <<<"$MAPPERS"; then
  "$KCADM" create "clients/$CLIENT_UUID/protocol-mappers/models" -r "$REALM" \
    -s name=mcp-resource-audience \
    -s protocol=openid-connect \
    -s protocolMapper=oidc-audience-mapper \
    -s consentRequired=false \
    -s 'config."included.custom.audience"=https://mcp.home.arpa/mcp' \
    -s 'config."id.token.claim"=false' \
    -s 'config."access.token.claim"=true' \
    -s 'config."introspection.token.claim"=true' >/dev/null
fi

printf 'Keycloak browser client ready: %s (Authorization Code + PKCE S256)\n' "$CLIENT_ID"
IN_CONTAINER
