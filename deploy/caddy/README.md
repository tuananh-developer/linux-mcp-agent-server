# Caddy reverse proxy and internal TLS runbook

Caddy (`caddy:2.11.7-alpine`) acts as the sole LAN-facing HTTPS reverse proxy and TLS terminator. Both upstream services (`127.0.0.1:3000` for the MCP server and `127.0.0.1:8080` for Keycloak) remain bound strictly to host loopback.

## Route allowlist

`deploy/caddy/Caddyfile` terminates HTTPS with `tls internal` for two hostnames configured via environment variables (`MCP_DOMAIN` and `AUTH_DOMAIN`):

1. **`{$MCP_DOMAIN}` (`mcp.home.arpa`)**:
   - Allowed paths forwarded to `127.0.0.1:3000`:
     - `/mcp`
     - `/.well-known/oauth-protected-resource/mcp`
   - All other paths return `404` (note that `/healthz` remains loopback-only on `127.0.0.1:3000/healthz` and is not exposed to the LAN).

2. **`{$AUTH_DOMAIN}` (`auth.home.arpa`)**:
   - Allowed LAN-facing OIDC paths forwarded to `127.0.0.1:8080`:
     - `/realms/linux-agent/.well-known/openid-configuration`
     - `/realms/linux-agent/protocol/openid-connect/token`
     - `/realms/linux-agent/protocol/openid-connect/certs`
   - Loopback requests (`remote_ip 127.0.0.1 ::1`) are forwarded to `127.0.0.1:8080` so the administrator can configure the Keycloak realm locally on the Ubuntu host.
   - All other LAN requests (including `/admin/*`, `/realms/master/*`, and `/realms/linux-agent/protocol/openid-connect/token/introspect`) return `404`.

No wildcard CORS headers are configured, and upstream ports are never published to LAN interfaces.

## Client trust of the Caddy internal root CA

Caddy generates an internal Root CA inside the `caddy-data` Docker volume when started. Clients on the LAN must trust the **public root certificate** only:

```bash
# On the Ubuntu host after Caddy starts and provisions certificates:
docker compose -f deploy/compose/compose.yaml --profile lan cp \
  caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-local-root.crt

# Copy caddy-local-root.crt to the test client machine and install it into the OS trust store:
sudo cp caddy-local-root.crt /usr/local/share/ca-certificates/linux-mcp-caddy-root.crt
sudo update-ca-certificates
```

> **Security rule:** Never export, copy, or commit `/data/caddy/pki/authorities/local/root.key` or any intermediate private key.

## Host firewall (UFW) rules

Restrict inbound TCP 443 at the Ubuntu host firewall to the designated LAN client IP or demo subnet only, and ensure ports `3000`, `8080`, and `5432` are never opened:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
# Replace 192.168.56.0/24 with your actual test client IP or LAN subnet:
sudo ufw allow from 192.168.56.0/24 to any port 443 proto tcp comment "MCP and OIDC HTTPS ingress"
sudo ufw enable
sudo ufw status verbose
```

## Verification commands

```bash
# Allowed MCP protected-resource metadata route:
curl --cacert ./caddy-local-root.crt -i https://mcp.home.arpa/.well-known/oauth-protected-resource/mcp

# Unlisted path on MCP domain must return HTTP 404:
curl --cacert ./caddy-local-root.crt -i https://mcp.home.arpa/healthz

# Allowed OIDC discovery route:
curl --cacert ./caddy-local-root.crt -fsS https://auth.home.arpa/realms/linux-agent/.well-known/openid-configuration | jq .issuer

# Admin console from a non-loopback LAN client must return HTTP 404:
curl --cacert ./caddy-local-root.crt -i https://auth.home.arpa/admin/
```
