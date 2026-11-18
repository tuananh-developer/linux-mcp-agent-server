# Infrastructure Docker Compose runbook

`deploy/compose/compose.yaml` manages supporting identity and TLS services on the Ubuntu 24.04 host. The Python MCP application runs natively under systemd and is not containerized.

## Services and network boundaries

| Service | Image | Network / port | Responsibility |
|---|---|---|---|
| `postgres` | `postgres:18.6-bookworm` | Private `identity-backend`; no published port | Keycloak persistence |
| `keycloak` | `quay.io/keycloak/keycloak:26.8.1` | Private network + `127.0.0.1:8080`; management port internal only | OAuth/OIDC and token introspection |
| `caddy` | `caddy:2.11.7-alpine` | Host network, optional `lan` profile | Internal TLS and allowlisted LAN routes |

PostgreSQL does not store MCP metrics or process snapshots. The application has no database.

## PostgreSQL 18 storage

The PostgreSQL 18 image uses a version-specific data directory under `/var/lib/postgresql`. The named volume must be mounted at that parent path:

```yaml
- keycloak-postgres:/var/lib/postgresql
```

For a fresh installation, verify that data survives a container recreation. If a previous installation used the older `/var/lib/postgresql/data` mount target with a PostgreSQL 18 image, back up the running database before changing the volume layout. Do not remove a named volume or old container until the Keycloak realm has been restored and verified.

## Secrets

```bash
cd deploy/compose
cp .env.example .env
chmod 0600 .env
openssl rand -base64 32
```

Use separate strong values for `POSTGRES_PASSWORD` and `KEYCLOAK_ADMIN_PASSWORD`. Store them in a secret manager or protected root-owned file. Never commit `.env`, database dumps or Caddy PKI private keys.

## Validate and start

```bash
docker compose --env-file .env -f compose.yaml config --quiet
docker compose --env-file .env -f compose.yaml up -d postgres keycloak
docker compose --env-file .env -f compose.yaml ps
```

PostgreSQL uses `pg_isready`. Keycloak uses its readiness endpoint via the container-internal management port 9000; no host port is published. Caddy depends on Keycloak being healthy and is gated behind the `lan` profile.

Configure the realm, install the MCP service and verify local token introspection before starting Caddy:

```bash
docker compose --env-file .env -f compose.yaml --profile lan up -d caddy
```

## Verify exposure

```bash
ss -lntp | grep -E ':(443|3000|8080|5432|9000)\\b'
```

MCP 3000 and Keycloak 8080 must remain loopback-only. PostgreSQL 5432 and Keycloak management 9000 must not be published. Only Caddy's intended HTTPS ingress should be reachable from the demo LAN.
