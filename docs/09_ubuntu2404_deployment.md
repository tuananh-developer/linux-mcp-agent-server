# Ubuntu 24.04 LTS deployment

This runbook describes the intended single-host deployment. Complete the checks in order. Do not expose the LAN-facing Caddy profile until local OAuth/resource validation and MCP health checks succeed.

## Host prerequisites

- Ubuntu 24.04 LTS x86_64 with systemd and journald.
- Python 3.15.2 managed by uv 0.13.8; CI also tests Python 3.14.10.
- Git, curl, build tools where a Python wheel is unavailable, Docker Engine and Docker Compose plugin.
- DNS or `/etc/hosts` entries resolving `mcp.home.arpa` and `auth.home.arpa` to this host.
- Firewall access to TCP 443 limited to the selected demo subnet/client addresses.

## 1. Prepare the repository and Python runtime

Install uv 0.13.8 using the approved installation method, then:

```bash
uv python install 3.15.2
git clone https://github.com/tuananh-developer/linux-mcp-agent-server.git
cd linux-mcp-agent-server
git checkout integration/finalize-ubuntu2404
uv sync --locked --no-dev
```

The deployment must use a reviewed `uv.lock`. Do not run `uv lock` on the production host as a substitute for a committed lockfile.

## 2. Start PostgreSQL and Keycloak

```bash
cd deploy/compose
cp .env.example .env
chmod 0600 .env
```

Replace the PostgreSQL and Keycloak administrator passwords with separate, strong random values obtained from a secure secret source. Do not commit `.env`.

Validate and start the identity services:

```bash
docker compose --env-file .env -f compose.yaml config --quiet
docker compose --env-file .env -f compose.yaml up -d postgres keycloak
docker compose --env-file .env -f compose.yaml ps
```

Wait until both PostgreSQL and Keycloak report healthy. The Keycloak readiness probe uses its internal management interface on container port 9000; this port is not published.

### PostgreSQL 18 named-volume note

The PostgreSQL 18 official image stores its version-specific data directory below `/var/lib/postgresql`. The Compose file mounts the named volume at that parent directory. For a fresh installation, verify persistence by writing a test record, recreating the PostgreSQL container and confirming the record remains.

For an installation that was previously started with an older volume target, **do not remove or recreate the named volume blindly**. Back up Keycloak first (for example, with a database dump), migrate/restore into the corrected volume layout, and verify the realm and clients before deleting any old container or volume.

## 3. Configure the Keycloak realm

Follow [the Keycloak runbook](../deploy/keycloak/README.md). Import `deploy/keycloak/realm-linux-agent.example.json` after replacing both placeholder client secrets in a local, ignored copy.

Configure:
- Realm: `linux-agent`.
- Resource server client: `linux-mcp-resource-server`.
- External MCP client: `linux-mcp-agent-client`.
- Base scope: `mcp.read`.
- Optional journal scope: `mcp.logs.read`.
- Canonical resource/audience: `https://mcp.home.arpa/mcp`.

Confirm the actual token and introspection payload contain the expected issuer, audience, client ID, expiration and scopes. Choose the introspection-cache TTL according to the acceptable revocation delay (no more than 300 seconds); document the selected value. Do not bypass the audience validation if the Keycloak mapper or resource indicator is incorrect.

## 4. Install and configure the native MCP service

Follow [the systemd runbook](../deploy/systemd/README.md). Create the dedicated `linux-mcp-agent` service account and install the service environment file with owner root, group linux-mcp-agent and mode 0640.

Set at least:
- `APP_ENV=production`
- `AUTH_MODE=keycloak`
- Exact MCP/Keycloak hostname and resource URLs
- `MCP_REQUIRED_AUDIENCE` equal to `MCP_RESOURCE_URI` after trailing-slash normalization
- `MCP_INTROSPECTION_CACHE_TTL_SECONDS` (default `30`, range `0`–`300`; set `0` to disable successful-introspection caching)
- Resource-server client ID and secret
- Allowed disk paths and log-source aliases

The service must bind to `127.0.0.1:3000`. Start it and verify locally:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now linux-mcp-agent
sudo systemctl status linux-mcp-agent
curl -fsS http://127.0.0.1:3000/healthz
```

Before proceeding, run a real authorized MCP Client request from the server host and verify that an invalid token is rejected.

## 5. Enable Caddy LAN ingress

Install the Caddy internal CA root into a local test trust store and configure the host firewall for the intended client subnet.

Start the LAN profile only after the local MCP service and Keycloak token verification work:

```bash
cd deploy/compose
docker compose --env-file .env -f compose.yaml --profile lan up -d caddy
docker compose --env-file .env -f compose.yaml ps
```

Distribute only the Caddy root certificate to authorized clients. Never copy the CA private key. From a second LAN device, verify DNS, HTTPS trust, MCP discovery and authenticated tool invocation.

## 6. Verify network and security boundaries

```bash
ss -lntp | grep -E ':(443|3000|8080|5432|9000)\\b'
systemctl show linux-mcp-agent -p User,Group,SupplementaryGroups
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml ps
```

Expected:
- 3000 and 8080 bound to loopback only.
- PostgreSQL 5432 is not published.
- Keycloak management 9000 is not published.
- Only intended HTTPS ingress is reachable from the LAN.
- systemd runs under the dedicated non-root account.
- Keycloak administration is unavailable from a second LAN device.
- Missing/invalid token, wrong issuer/audience, missing base scope and missing log scope fail closed.

## 7. Run acceptance and performance checks

Run code checks and the actual HTTP integration test in CI. On the designated Ubuntu 24.04 host, run the benchmark with a valid bearer token:

```bash
MCP_BENCHMARK_URL=https://mcp.home.arpa/mcp \
MCP_BENCHMARK_ACCESS_TOKEN='<read token>' \
MCP_BENCHMARK_LOG_ALIAS=ssh \
uv run python scripts/benchmark_mcp.py --iterations 100
```

Store the JSON output under `reports/acceptance/` and complete the acceptance checklist. Record host model/CPU/RAM, OS/kernel, Python and SDK versions, sample count, p50/p95/p99, failures and limitations. The p95 target is at or below 2 seconds per tool, excluding external LLM inference.

## Rollback

Record the deployed commit before an upgrade. If service health or acceptance checks fail, check out the previous reviewed commit, restore its locked dependencies and service unit, restart the service, and verify `/healthz`. Do not delete the Keycloak database volume as part of an application rollback.
