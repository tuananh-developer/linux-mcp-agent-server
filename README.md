# Linux MCP Agent Server

A read-only Linux observability MCP server for external Agentic AI clients. Built with Python 3.15.2 (the latest stable Python release on 2026-11-02) and the official MCP Python SDK 2.3.0. CI checks both Python 3.14.10 and 3.15.2 because some upstream package classifiers have not yet caught up with the newest interpreter. The primary acceptance environment is **Ubuntu 24.04 LTS**.

## Browser dashboard

Open `/` or `/dashboard` for live CPU, RAM, disk, network, process, service, port and alert views. The optional AI assistant is available at `/assistant`. Dashboard telemetry is requested through authenticated MCP tools; it does not require an LLM, database, or external API key. See [docs/12_dashboard.md](docs/12_dashboard.md) for data flow and security details.

## Scope

The server exposes:

| Primitive | Name | Purpose |
|---|---|---|
| Tool | `get_system_metrics` | CPU, memory, load average and uptime |
| Tool | `get_disk_usage` | Allowlisted filesystem capacity |
| Tool | `list_processes` | Bounded PID/name/CPU/RAM snapshot |
| Tool | `read_allowed_log` | Allowlisted journald unit aliases only |
| Tool | `get_network_stats` | Per-interface traffic counters and link state |
| Tool | `get_service_status` | Read-only status of allowlisted systemd services |
| Tool | `check_port` | Single local TCP listener check on loopback |
| Tool | `get_system_alerts` | CPU, memory and allowlisted-disk threshold alerts |
| Resource | `linux://system/summary` | High-level JSON system and network summary |
| Prompt | `health_check` | Safe, read-only health-check instructions |

The AI assistant integration is optional; its model gateway uses the same authenticated MCP tools. The dashboard itself does not require an LLM, database, or provider API key. No arbitrary shell, destructive system operation, process command line or environment values are exposed.

## Architecture

- Python MCP service runs natively on the Linux host under systemd and binds to `127.0.0.1:3000`.
- Caddy 2.11.7 terminates TLS and exposes only the MCP endpoint and required protected-resource metadata route to the LAN.
- Keycloak 26.8.1 issues OAuth access tokens; the MCP service validates them using RFC 7662 introspection and exact issuer/resource/audience/scope checks.
- PostgreSQL 18.6 stores Keycloak data only. It is not an application database.
- Docker Compose 5.6.1 runs Caddy, Keycloak and PostgreSQL; the MCP service is not containerized.

## Version baseline (checked 2026-11-02)

| Component | Version |
|---|---:|
| Python | 3.15.2 (default); CI also checks 3.14.10 |
| Hatchling build backend | 1.33.0 |
| Official MCP Python SDK (`mcp`) | 2.3.0 |
| psutil | 7.2.2 |
| Pydantic | 2.14.2 |
| Starlette | 1.10.0 |
| Uvicorn | 0.54.0 |
| uv | 0.13.6 |
| pytest / pytest-asyncio | 9.2.0 / 1.4.1 |
| Ruff / Pyright | 0.17.3 / 1.1.414 |
| Caddy | 2.11.7 |
| Keycloak | 26.8.1 |
| PostgreSQL | 18.6 |
| Docker Compose CLI | 5.6.1 |

Exact direct Python dependencies are pinned in `pyproject.toml`. Generate `uv.lock` with `uv lock` on a network-connected development machine, review and commit it before production deployment; CI currently resolves transitive dependencies from the exact direct pins.

## Local development

Install uv 0.13.6 and Python 3.15.2:

```bash
curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/0.13.6/install.sh | sh
uv python install 3.15.2
uv lock
uv sync --all-groups
cp .env.example .env
set -a; source .env; set +a
uv run python -m linux_mcp_agent
```

The local `.env.example` uses `AUTH_MODE=disabled` and loopback only. Never expose this development mode to the LAN.

## Quality checks

```bash
uv run ruff check .
uv run pyright
uv run pytest
```

## LAN deployment

See:

- `docs/09_ubuntu2404_deployment.md`
- `docs/08_authorization_tls_design.md`
- `deploy/keycloak/README.md`
- `deploy/systemd/README.md`

The LAN profile requires `AUTH_MODE=keycloak`, trusted Caddy internal CA, a configured Keycloak realm/client, and firewall rules limiting TCP 443. The MCP app and Keycloak bind only to loopback; PostgreSQL is internal to Docker. Compose deliberately gates Caddy behind the `lan` profile: start and validate PostgreSQL/Keycloak and the authenticated MCP service first, then explicitly run `docker compose --profile lan up -d caddy`.

## Security and known acceptance gate

Keycloak 26.8.1 labels Resource Indicators experimental for the newest MCP protocol revision. The server fails closed unless the token has the exact configured MCP audience/resource. Do not disable audience validation to work around an integration problem. Keep LAN exposure closed until a real integration test confirms `resource` -> `aud`, introspection claims, required scopes and cross-device TLS trust.

The `systemd-journal` supplementary group enables journal access but is broader than the MCP alias list; this residual privilege is documented and must be reviewed during deployment.

## Live demo

To start the local Keycloak/PostgreSQL/Caddy stack and ensure the MCP service is running, use:

```bash
bash scripts/start-demo.sh
```

In a second terminal, run the real Keycloak-authenticated MCP acceptance client:

```bash
uv run python scripts/demo_live.py
```

It discovers and calls all eight tools, reads `linux://system/summary`, and retrieves the `health_check` prompt. See [docs/10_live_demo.md](docs/10_live_demo.md) for one-time credential setup and TLS trust notes. The client keeps the access token in memory and never prints or saves credentials.

