# Authorization and TLS design

## Roles

- Keycloak is the OAuth 2.1 authorization server.
- Linux MCP Agent Server is a resource server. It never issues a token.
- External Agent/MCP Client obtains an access token using the configured client flow and sends `Authorization: Bearer ...`.

## Browser login

The Linux Observatory is a public OAuth client named `linux-observatory-browser`. It uses Authorization Code flow with PKCE S256; it has no client secret and does not enable password or implicit grants. The browser obtains a short-lived MCP-audience token after an interactive user login. Access and refresh tokens stay in browser memory; the browser never receives the resource-server introspection secret or machine-client secret.

`scripts/configure-browser-client.sh` provisions this client idempotently in the existing `linux-agent` realm during demo startup. The Keycloak built-in `basic` and project `mcp.read` scopes are attached by default; `mcp.logs.read` is optional and requested by the UI. The built-in `basic` scope supplies the Subject (`sub`) protocol mapper so Keycloak includes the authenticated user subject in both the access token and token-introspection response. The setup script explicitly attaches `basic` for existing realms as well as new ones, because the realm template defines its own default scope list. The browser client has the MCP origin as its only web origin and `https://mcp.home.arpa/*` as its redirect pattern. Caddy exposes only OIDC discovery, authorization, token, JWKS, login-action and static login-theme routes to browser clients; Keycloak admin routes remain loopback-only. An administrator creates a realm user once for interactive login.

## Token validation

The MCP SDK requires `mcp.read` globally. `KeycloakIntrospectionVerifier` calls `MCP_INTROSPECTION_URL` on the private loopback Keycloak HTTP listener using a confidential resource-server client; Caddy never publishes token introspection to the LAN. It accepts a token only when `active=true`, `iss` exactly equals the configured issuer, `exp` exists and is in the future, `nbf` is not in the future, `aud` contains the exact canonical MCP resource URI, `client_id` exists, and `mcp.read` is granted. It returns `AccessToken.resource` equal to `MCP_RESOURCE_URI`; `AuthSettings.validate_token_resource=True` enforces the same resource at SDK level.

`read_allowed_log` additionally checks `mcp.logs.read`. This produces a tool-level insufficient-scope error; it does not claim that the entire HTTP request was rejected at the gateway.

## Resource indicator

Canonical resource URI: `https://mcp.home.arpa/mcp`. The MCP client must request `resource` with exactly this value and a scope containing the needed scopes. Keycloak 26.8.1 requires the experimental `resource-indicators` feature and a matching `resource_url` attribute on the resource-server client. The integration is not considered accepted until the token's `aud` and introspection response are verified on the deployed realm.

## TLS and LAN

Caddy 2.11.7 uses `tls internal` for both `mcp.home.arpa` and `auth.home.arpa`. Export only the Caddy root certificate to client trust stores; never export the CA private key. MCP backend `127.0.0.1:3002`, Keycloak `127.0.0.1:8080`, PostgreSQL internal Docker network. UFW should allow TCP 443 only from the selected demo subnet/client addresses.

## Reverse proxy route allowlist

Caddy forwards MCP `/mcp` and `/.well-known/oauth-protected-resource/mcp`. On the auth hostname, expose only realm OIDC metadata, token endpoint and JWKS endpoint. Admin console/API routes are loopback-only; unmatched LAN paths return 404. No wildcard CORS.

## Failure behavior

Missing/inactive/expired token, wrong issuer/audience/resource or missing base scope must not execute a tool. Missing log scope must not execute `journalctl`. Untrusted TLS CA fails at the client. Unknown Host/Origin and unlisted Caddy path are rejected before tool invocation.
