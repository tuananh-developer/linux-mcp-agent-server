# Infrastructure Docker Compose runbook

`deploy/compose/compose.yaml` manages the supporting identity and TLS reverse-proxy containers on the Ubuntu 24.04 host. The Python MCP server itself runs natively under `systemd` (`deploy/systemd/linux-mcp-agent.service`) and is not containerized.

## Services and security controls

| Service | Image | Network & Port Binding | Controls |
|---|---|---|---|
| `postgres` | `postgres:18.6-bookworm` | Internal network `identity-backend` only; no host ports published | Named volume `keycloak-postgres`, `pg_isready` healthcheck, `no-new-privileges:true` |
| `keycloak` | `quay.io/keycloak/keycloak:26.8.1` | `identity-backend` + loopback port `127.0.0.1:8080:8080` | Waits for healthy `postgres`, enables `resource-indicators`, `KC_HOSTNAME_STRICT=true`, `no-new-privileges:true` |
| `caddy` | `caddy:2.11.7-alpine` | `network_mode: host`, gated behind `--profile lan` | Read-only `Caddyfile` mount, `cap_drop: ALL`, `cap_add: NET_BIND_SERVICE`, `no-new-privileges:true` |

## Environment setup (secrets management)

1. Copy the template to `.env` (which is git-ignored):
   ```bash
   cd deploy/compose
   cp .env.example .env
   chmod 0600 .env
   ```
2. Replace `POSTGRES_PASSWORD` and `KEYCLOAK_ADMIN_PASSWORD` in `.env` with strong random values:
   ```bash
   openssl rand -base64 32
   ```
3. Never commit `.env`, database dumps, or Caddy PKI private keys to Git.

## Validate and start the stack

1. Validate the Compose configuration:
   ```bash
   cd deploy/compose
   docker compose --env-file .env.example -f compose.yaml config --quiet
   ```
2. Start PostgreSQL and Keycloak first (Caddy remains off until Keycloak and the MCP service are configured and verified):
   ```bash
   docker compose --env-file .env -f compose.yaml up -d postgres keycloak
   docker compose --env-file .env -f compose.yaml ps
   ```
3. Configure the `linux-agent` realm and clients following `../keycloak/README.md`, and start the native `linux-mcp-agent.service` following `../systemd/README.md`.
4. Once local introspection and audience validation succeed, start the LAN reverse proxy:
   ```bash
   docker compose --env-file .env -f compose.yaml --profile lan up -d caddy
   ```

## Verify socket exposure

Confirm that PostgreSQL (`5432`) is not bound on the host and that MCP (`3000`) and Keycloak (`8080`) bind strictly to `127.0.0.1`:

```bash
ss -lntp | grep -E ':(443|3000|8080|5432)\b'
```
