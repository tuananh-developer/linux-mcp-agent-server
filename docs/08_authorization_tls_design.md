# Authorization and TLS design

## Roles

- **Keycloak 26.8.1:** OAuth/OIDC authorization server. It authenticates configured clients and issues access tokens.
- **Linux MCP Agent Server:** OAuth resource server. It never issues tokens; it validates access tokens using RFC 7662 introspection.
- **Caddy 2.11.7:** TLS terminator and LAN reverse proxy. It does not replace application-level token validation.
- **PostgreSQL 18.6:** Keycloak persistence only.

## Canonical resource configuration

The canonical protected resource is `https://mcp.home.arpa/mcp`.

`MCP_RESOURCE_URI` and `MCP_REQUIRED_AUDIENCE` must be identical. Configuration rejects a mismatch because the MCP SDK resource binding and the introspected token audience must refer to the same resource. The external MCP Client requests this resource from Keycloak and sends the resulting bearer access token to the MCP endpoint.

The Keycloak realm template includes:
- Realm `linux-agent`.
- Base client scope `mcp.read`.
- Optional journal scope `mcp.logs.read`.
- Confidential resource-server client `linux-mcp-resource-server`.
- Example external client `linux-mcp-agent-client` with a resource audience mapper.

The template contains placeholder secrets only. Replace them using a secure secret source before importing the realm. Do not commit generated realm exports or runtime secrets.

## Token validation flow

1. The MCP SDK extracts the bearer token from the HTTP request.
2. `KeycloakIntrospectionVerifier` sends the token to the loopback-only `MCP_INTROSPECTION_URL` using the resource-server client's Basic credentials.
3. The verifier fails closed if the endpoint is unavailable, the response is malformed or the token is invalid.
4. `validate_introspection_payload` validates:
   - `active is true`;
   - exact configured `iss`;
   - mandatory, finite `exp` later than the current time;
   - optional finite `nbf` not later than the current time;
   - exact configured MCP resource in `aud`;
   - required `mcp.read` scope;
   - a non-empty client ID.
5. The verifier supplies the canonical resource to the MCP SDK. `AuthSettings.validate_token_resource=True` enforces the same resource binding at SDK level.
6. `read_allowed_log` independently checks for `mcp.logs.read` before it runs journalctl. Missing permission never invokes the journal reader.

Introspection responses and journal content are treated as untrusted input. Tokens, client secrets and raw authorization headers must not be written to application logs.

## TLS and LAN ingress

Caddy uses `tls internal` for `mcp.home.arpa` and `auth.home.arpa`. It forwards:
- MCP `/mcp` and the MCP protected-resource metadata path on the MCP hostname.
- Only OIDC discovery, token and JWKS endpoints on the Keycloak hostname.
- Keycloak administration paths only when the client is loopback.

Unmatched hosts/paths return 404. Do not add wildcard routes or wildcard CORS to make an untrusted client work.

The Caddy internal CA root certificate must be installed in each trusted MCP client. The CA private key must remain on the server and must never be exported.

## Network exposure

- MCP backend: `127.0.0.1:3000`.
- Keycloak HTTP: `127.0.0.1:8080`.
- PostgreSQL: private Docker network only; no host port.
- Caddy: host network, intended LAN ingress on HTTPS only.
- Keycloak management/health port 9000: container-internal; not published to the host or LAN.

Firewall policy should allow TCP 443 only from the selected demo subnet/client addresses. Do not expose 3000, 8080 or 5432.

## Residual risks and acceptance

Keycloak Resource Indicators are marked experimental in the pinned Keycloak version. The feature must be verified with the imported realm and the actual token response; do not disable audience/resource validation to work around a mismatch.

Membership in `systemd-journal` provides broader OS-level journal visibility than the MCP alias list. The application enforces the allowlist and bounded reader, but this residual service-account privilege must be reviewed on the acceptance host.

Before enabling LAN ingress, verify a real token's `iss`, `aud`, scopes and introspection result; verify TLS trust from a second device; verify admin routes are unavailable from LAN; and record the evidence and limitations.
