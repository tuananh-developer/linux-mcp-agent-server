# Caddy reverse proxy and internal TLS runbook

Caddy is the only LAN-facing HTTPS ingress. MCP Server and Keycloak remain bound to host loopback.

## Route allowlist

- `{$MCP_DOMAIN}`: forwards only `/mcp` and `/.well-known/oauth-protected-resource/mcp` to `127.0.0.1:3002`. Other paths return 404. The local `/healthz` endpoint is not exposed to the LAN.
- `{$AUTH_DOMAIN}`: forwards the Linux Agent realm's OIDC discovery, token and certificate endpoints to `127.0.0.1:8080`. Requests from loopback are also forwarded for local administration. Other remote paths, including the Admin Console and introspection endpoint, return 404.

No wildcard CORS headers are configured. Do not publish MCP 3002, Keycloak 8080 or PostgreSQL 5432 to LAN interfaces.

## Trust the internal CA

Caddy creates its local root CA in the `caddy-data` volume. Export only the public root certificate:

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml --profile lan cp \
  caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-local-root.crt
```

Install that certificate on an authorized client using its operating-system trust-store procedure. Never export or commit `root.key` or any intermediate private key.

## Verify routes

```bash
curl --cacert ./caddy-local-root.crt -i https://mcp.home.arpa/.well-known/oauth-protected-resource/mcp
curl --cacert ./caddy-local-root.crt -i https://mcp.home.arpa/healthz
curl --cacert ./caddy-local-root.crt -fsS https://auth.home.arpa/realms/linux-agent/.well-known/openid-configuration
curl --cacert ./caddy-local-root.crt -i https://auth.home.arpa/admin/
```

Expected: protected-resource metadata and OIDC discovery are reachable; the MCP LAN `/healthz` path and remote Keycloak Admin Console return 404.
