# Caddy reverse proxy — implementation brief

> No runnable Caddyfile is present on `team-handoff`. Member 2 implements it; member 3 independently tests it.

## Target requirements

- Pin the selected Caddy 2.11.x image and document its exact version.
- Terminate HTTPS using the internal CA for `mcp.home.arpa` and `auth.home.arpa`.
- Forward only the MCP endpoint and protected-resource metadata route to the loopback MCP service.
- On the Keycloak hostname, expose only OIDC discovery, token issuance and JWKS endpoints.
- Keep Keycloak administration and unmatched paths unavailable from LAN clients; return 404 for unlisted routes.
- Do not use wildcard CORS or publish upstream service ports.
- Document client trust of the Caddy root certificate. Never export its private key.
- Restrict inbound TCP 443 at the host firewall to the demo LAN/client addresses.

## Acceptance

Test allowed and denied host/path combinations, verify TLS trust from a second LAN client, and prove that the Keycloak admin routes are not reachable from that client.
