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

# The client-scopes collection does not filter by ?name=. Fetch the catalog
# once and select the exact ID locally instead of accidentally using the last
# scope in the realm.
SCOPE_CATALOG="$("$KCADM" get client-scopes -r "$REALM" --fields id,name --format csv --noquotes)"

for SCOPE_NAME in mcp.read mcp.logs.read; do
  SCOPE_ID=""
  while IFS=, read -r candidate_id candidate_name; do
    if [[ "$candidate_name" == "$SCOPE_NAME" ]]; then
      SCOPE_ID="$candidate_id"
      break
    fi
  done <<< "$SCOPE_CATALOG"

  [[ -n "$SCOPE_ID" ]] || {
    echo "ERROR: Required Keycloak client scope '$SCOPE_NAME' is missing from realm '$REALM'." >&2
    exit 1
  }

  if [[ "$SCOPE_NAME" == "mcp.read" ]]; then
    RELATION=default-client-scopes
    OPPOSITE_RELATION=optional-client-scopes
  else
    RELATION=optional-client-scopes
    OPPOSITE_RELATION=default-client-scopes
  fi

  # Keep each custom scope in exactly the intended attachment category.
  OPPOSITE_SCOPES="$("$KCADM" get "clients/$CLIENT_UUID/$OPPOSITE_RELATION" -r "$REALM")"
  if grep -Fq "$SCOPE_NAME" <<<"$OPPOSITE_SCOPES"; then
    "$KCADM" delete "clients/$CLIENT_UUID/$OPPOSITE_RELATION/$SCOPE_ID" -r "$REALM"
  fi

  CURRENT_SCOPES="$("$KCADM" get "clients/$CLIENT_UUID/$RELATION" -r "$REALM")"
  if ! grep -Fq "$SCOPE_NAME" <<<"$CURRENT_SCOPES"; then
    # This association endpoint supports PUT but not a GET on an individual
    # association. -n tells kcadm to skip its default GET/merge preflight.
    "$KCADM" update "clients/$CLIENT_UUID/$RELATION/$SCOPE_ID" -r "$REALM" -n >/dev/null
  fi

  VERIFIED_SCOPES="$("$KCADM" get "clients/$CLIENT_UUID/$RELATION" -r "$REALM")"
  grep -Fq "$SCOPE_NAME" <<<"$VERIFIED_SCOPES" || {
    echo "ERROR: Failed to attach '$SCOPE_NAME' to $CLIENT_ID/$RELATION." >&2
    exit 1
  }
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

printf 'Verified Keycloak browser client: %s (mcp.read default, mcp.logs.read optional, PKCE S256)\n' "$CLIENT_ID"
IN_CONTAINER
\r'}"
    if [[ "$candidate_name" == "$SCOPE_NAME" ]]; then
      SCOPE_ID="$candidate_id"
      break
    fi
  done <<< "$SCOPE_CATALOG"
  [[ -n "$SCOPE_ID" ]] || {
    echo "ERROR: Required Keycloak client scope '$SCOPE_NAME' is missing from realm '$REALM'." >&2
    exit 1
  }

  if [[ "$SCOPE_NAME" == "mcp.read" ]]; then
    RELATION=default-client-scopes
    OPPOSITE_RELATION=optional-client-scopes
  else
    RELATION=optional-client-scopes
    OPPOSITE_RELATION=default-client-scopes
  fi

  # Keep each custom scope in exactly the intended attachment category.
  OPPOSITE_SCOPES="$("$KCADM" get "clients/$CLIENT_UUID/$OPPOSITE_RELATION" -r "$REALM")"
  if grep -Fq "$SCOPE_NAME" <<<"$OPPOSITE_SCOPES"; then
    "$KCADM" delete "clients/$CLIENT_UUID/$OPPOSITE_RELATION/$SCOPE_ID" -r "$REALM"
  fi

  CURRENT_SCOPES="$("$KCADM" get "clients/$CLIENT_UUID/$RELATION" -r "$REALM")"
  if ! grep -Fq "$SCOPE_NAME" <<<"$CURRENT_SCOPES"; then
    # This association endpoint supports PUT but not a GET on an individual
    # association. -n tells kcadm to skip its default GET/merge preflight.
    "$KCADM" update "clients/$CLIENT_UUID/$RELATION/$SCOPE_ID" -r "$REALM" -n >/dev/null
  fi

  VERIFIED_SCOPES="$("$KCADM" get "clients/$CLIENT_UUID/$RELATION" -r "$REALM")"
  grep -Fq "$SCOPE_NAME" <<<"$VERIFIED_SCOPES" || {
    echo "ERROR: Failed to attach '$SCOPE_NAME' to $CLIENT_ID/$RELATION." >&2
    exit 1
  }
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

printf 'Verified Keycloak browser client: %s (mcp.read default, mcp.logs.read optional, PKCE S256)\n' "$CLIENT_ID"
IN_CONTAINER
