# Linux MCP Agent Server

A read-only Linux observability MCP server for external Agentic AI clients. Built with Python 3.15.2 (the latest stable Python release on 2026-11-02) and the official MCP Python SDK 2.3.0. CI checks both Python 3.14.10 and 3.15.2 because some upstream package classifiers have not yet caught up with the newest interpreter. The primary acceptance environment is **Ubuntu 24.04 LTS**.

## Browser dashboard

Open `/` or `/dashboard` for live CPU, RAM, swap, disk/inode, PSI pressure, network, process, service, port and alert views. The optional AI assistant is available at `/assistant`. Dashboard telemetry is requested through authenticated MCP tools; it does not require an LLM, database, or external API key. See [docs/12_dashboard.md](docs/12_dashboard.md) for data flow and security details.

## Fresh installation (Ubuntu 24.04 LTS)

For a new host, the recommended route is the automated installer. It provisions the Docker infrastructure (PostgreSQL, Keycloak and Caddy), installs the native MCP service, creates the first dashboard account, generates installation secrets, initializes the encrypted provider vault, and verifies the local HTTPS health endpoint.

```bash
git clone https://github.com/tuananh-developer/linux-mcp-agent-server.git
cd linux-mcp-agent-server
sudo bash scripts/install.sh
```

The installer currently supports Ubuntu 24.04 LTS on amd64 and arm64. It asks for the host's LAN IPv4 address and the first dashboard username/password. It uses the project's fixed `mcp.home.arpa` and `auth.home.arpa` hostnames because the browser OAuth client is configured for those origins.

When installation completes, open `https://mcp.home.arpa/dashboard` on the host. Other LAN devices must resolve both hostnames to the server's LAN IP and trust the Caddy root CA at `/etc/linux-mcp-agent/caddy-root.crt`. The installer does not change the firewall: allow TCP 443 only from trusted LAN clients, and keep ports 3002, 8080 and 5432 private.

The vault master key and generated service secrets are stored in protected system directories; do not delete them. The first dashboard user signs in with the username/password entered during setup, then configures an AI provider and saves its API key from the dashboard.

Management commands (run from the repository clone):

```bash
sudo bash scripts/doctor.sh
sudo systemctl restart linux-mcp-agent.service
sudo bash scripts/upgrade.sh
sudo bash scripts/uninstall.sh
```

The upgrade keeps the Keycloak database, server configuration and provider vault. Uninstall preserves data by default; `--purge-data` requires a second explicit confirmation and permanently deletes it. If setup stops part-way through, rerun `sudo bash scripts/install.sh --resume` from the same clone; generated secrets and existing database/vault data are reused.

See [docs/13_installation.md](docs/13_installation.md) for the full setup, client trust and recovery runbook. The manual systemd and local demo paths remain available for operators and development.

## Scope

The server exposes:

| Primitive | Name | Purpose |
|---|---|---|
| Tool | `get_system_metrics` | CPU, memory, load average and uptime |
| Tool | `get_swap_usage` | Swap capacity and cumulative swap-in/swap-out counters |
| Tool | `get_disk_usage` | Allowlisted filesystem byte capacity |
| Tool | `get_filesystem_inode_usage` | Inode usage for allowlisted mount points |
| Tool | `list_processes` | Bounded PID/name/CPU/RAM snapshot |
| Tool | `read_allowed_log` | Allowlisted journald unit aliases only |
| Tool | `get_network_stats` | Per-interface traffic counters and link state |
| Tool | `get_resource_pressure` | Linux PSI CPU, memory and I/O stall averages |
| Tool | `get_service_status` | Read-only status of allowlisted systemd services |
| Tool | `check_port` | Single local TCP listener check on loopback |
| Tool | `get_system_alerts` | CPU, memory and allowlisted-disk threshold alerts |
| Resource | `linux://system/summary` | High-level JSON system and network summary |
| Prompt | `health_check` | Safe, read-only health-check instructions |

The AI assistant is optional and supports user-selected Gemini, OpenAI, OpenRouter, Anthropic, or local Ollama models. Hosted provider API keys can be saved per Keycloak subject in a server-side AES-256-GCM encrypted credential vault. Production systemd installs deliver the master key through systemd credentials; demo mode keeps a per-installation key in the signed-in user's private config directory. Ollama does not require an API key. The dashboard itself does not require an LLM, database, or provider API key. No arbitrary shell, destructive system operation, process command line or environment values are exposed.

## Architecture

- Python MCP service runs natively on the Linux host and binds to `127.0.0.1:3002`. Production installs can manage it with systemd; the demo launcher can run it as the signed-in user without installing a system service.
- Caddy 2.11.7 terminates TLS and exposes the read-only dashboard, assistant, MCP endpoint, health check, and required protected-resource metadata route to the LAN.
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

After pulling updated code, restart the demo-managed server with one command:

```bash
bash scripts/restart-demo.sh
```

The restart helper stops only a process launched from this repository and then starts the server again. It also delegates to the systemd service when that production unit is installed. The API-key vault is initialized automatically; users save or remove hosted provider credentials from the dashboard without running vault-management commands.

In a second terminal, run the real Keycloak-authenticated MCP acceptance client:

```bash
uv run python scripts/demo_live.py
```

It discovers and calls all eleven tools, reads `linux://system/summary`, and retrieves the `health_check` prompt. See [docs/10_live_demo.md](docs/10_live_demo.md) for one-time credential setup and TLS trust notes. The client keeps the access token in memory and never prints or saves credentials.

