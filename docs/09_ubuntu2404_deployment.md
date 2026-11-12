# Ubuntu 24.04 LTS deployment

> **Deployment target only on `team-handoff`:** the Compose model, Caddyfile, systemd unit and production environment template are intentionally absent. Member 2 must implement them; member 3 must validate the actual deployment. The commands below are not runnable until those deliverables exist.

## Host prerequisites

- Ubuntu 24.04 LTS x86_64, systemd and journald.
- Python 3.15.2 (managed by uv 0.13.6; CI also checks 3.14.10), Git, curl, build tools for compiling C extensions where a wheel is unavailable.
- Docker Engine + Docker Compose plugin 5.6.1 for Keycloak, PostgreSQL and Caddy only.
- Firewall: allow TCP 443 only from the selected LAN subnet/client IP. Do not expose 3000, 8080 or 5432.

## Prepare Python environment

```bash
curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/0.13.6/install.sh | sh
uv python install 3.15.2
uv lock
uv sync --all-groups
uv run ruff check .
uv run pyright
uv run pytest
```

Commit `uv.lock` after resolving dependencies on a network-connected development machine. The project pins direct dependencies in `pyproject.toml`.

## Start infrastructure

```bash
cd deploy/compose
cp .env.example .env
# Edit all secrets before starting.
# Start identity storage and Keycloak first. Caddy is intentionally profile-gated.
docker compose --env-file .env -f compose.yaml up -d postgres keycloak
```

Configure the `linux-agent` realm and machine clients as described in `../keycloak/README.md`. Install the Caddy internal CA root on each test client. Ensure DNS or `/etc/hosts` resolves both service hostnames to the Ubuntu host. Set `APP_ENV=production` and `AUTH_MODE=keycloak` in `/etc/linux-mcp-agent/server.env`, start the MCP service, and verify real OAuth introspection/audience checks before opening LAN ingress. Only then start Caddy:

```bash
docker compose --env-file .env -f compose.yaml --profile lan up -d caddy
```

## Install the MCP service

Follow `deploy/systemd/README.md`. The MCP service binds to loopback only, uses `AUTH_MODE=keycloak`, and reads `/etc/linux-mcp-agent/log-sources.json`.

## Acceptance checks

- `curl http://127.0.0.1:3000/healthz` returns healthy.
- Keycloak OIDC discovery is reachable over trusted HTTPS.
- Access token contains the canonical MCP audience and required scope.
- From a second LAN host, a valid MCP client can initialize and list tools/resources/prompts.
- Invalid token, wrong audience, missing scopes and admin UI requests from LAN are rejected.
- `systemctl show linux-mcp-agent -p User,Group,SupplementaryGroups` confirms the service account.
- `ss -lntp` confirms 3000 and 8080 are bound to loopback only; PostgreSQL is not published.
