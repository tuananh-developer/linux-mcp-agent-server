# Authorization and TLS design

> **Design reference only on `team-handoff`:** OAuth and TLS implementation have deliberately been returned to member 2. The server on this branch has no OAuth verifier or LAN ingress. Do not treat the design below as an implemented security control.

## Roles

- Keycloak is the OAuth 2.1 authorization server.
- Linux MCP Agent Server is a resource server. It never issues a token.
- External Agent/MCP Client obtains an access token using the configured client flow and sends `Authorization: Bearer ...`.

## Token validation

The MCP SDK requires `mcp.read` globally. `KeycloakIntrospectionVerifier` calls `MCP_INTROSPECTION_URL` on the private loopback Keycloak HTTP listener using a confidential resource-server client; Caddy never publishes token introspection to the LAN. It accepts a token only when `active=true`, `iss` exactly equals the configured issuer, `exp` exists and is in the future, `nbf` is not in the future, `aud` contains the exact canonical MCP resource URI, `client_id` exists, and `mcp.read` is granted. It returns `AccessToken.resource` equal to `MCP_RESOURCE_URI`; `AuthSettings.validate_token_resource=True` enforces the same resource at SDK level.

`read_allowed_log` additionally checks `mcp.logs.read`. This produces a tool-level insufficient-scope error; it does not claim that the entire HTTP request was rejected at the gateway.

## Resource indicator

`MCP_RESOURCE_URI` and `MCP_REQUIRED_AUDIENCE` must be exactly equal after removing trailing slashes. Configuration loading rejects a mismatch before the server starts. If omitted, `MCP_REQUIRED_AUDIENCE` defaults to the normalized resource URI.

Canonical resource URI: `https://mcp.home.arpa/mcp`. The MCP client must request `resource` with exactly this value and a scope containing the needed scopes. Keycloak 26.8.1 requires the experimental `resource-indicators` feature and a matching `resource_url` attribute on the resource-server client. The integration is not considered accepted until the token's `aud` and introspection response are verified on the deployed realm.

## Introspection cache and revocation

Successful introspection is cached in memory for `MCP_INTROSPECTION_CACHE_TTL_SECONDS` (default 30 seconds, allowed range 0–300). Each entry expires at the earlier of that TTL or the token's expiry. Revoking a token or removing its scopes in Keycloak does not invalidate an existing cache entry immediately: previously validated authorization can remain usable for up to the configured TTL, at most 300 seconds, bounded by token expiry. Set `MCP_INTROSPECTION_CACHE_TTL_SECONDS=0` to disable caching and introspect every verification. This increases Keycloak traffic and makes verification depend on its availability. Failed verification responses are not cached.

## TLS and LAN

Caddy 2.11.7 uses `tls internal` for both `mcp.home.arpa` and `auth.home.arpa`. Export only the Caddy root certificate to client trust stores; never export the CA private key. MCP backend `127.0.0.1:3000`, Keycloak `127.0.0.1:8080`, PostgreSQL internal Docker network. UFW should allow TCP 443 only from the selected demo subnet/client addresses.

## Reverse proxy route allowlist

Caddy forwards MCP `/mcp` and `/.well-known/oauth-protected-resource/mcp`. On the auth hostname, expose only realm OIDC metadata, token endpoint and JWKS endpoint. Admin console/API routes are loopback-only; unmatched LAN paths return 404. No wildcard CORS.

## Failure behavior

Missing/inactive/expired token, wrong issuer/audience/resource or missing base scope must not execute a tool. Missing log scope must not execute `journalctl`. Untrusted TLS CA fails at the client. Unknown Host/Origin and unlisted Caddy path are rejected before tool invocation.
