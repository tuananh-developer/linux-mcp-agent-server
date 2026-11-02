# Read this first

**Linux MCP Agent Server** is a read-only MCP server for Linux observability. It does not host an LLM and does not implement an Agent runtime. The external Agent/MCP Client owns model selection, inference, tool selection, credentials and provider fallback.

## Locked baseline (02/11/2026)

- Runtime: Python 3.15.2, pinned in `.python-version`; CI checks Python 3.15.2 and 3.14.10. Python 3.14 is the minimum supported runtime. Some upstream package classifiers may lag Python 3.15, so compatibility is accepted only while the full CI matrix remains green.
- MCP: official `mcp` Python SDK 2.3.0; protocol line follows SDK 2.x and the 2026-07-28 specification.
- Linux acceptance target: Ubuntu 24.04 LTS x86_64.
- Server transport: Streamable HTTP at `/mcp`, local backend `127.0.0.1:3000`.
- LAN edge: Caddy 2.11.7 with internal TLS for `mcp.home.arpa` and `auth.home.arpa`.
- Authorization: Keycloak 26.8.1; the server introspects access tokens and validates issuer, expiry, audience/resource and scopes.
- Database: PostgreSQL 18.6 is only for Keycloak; the MCP server has no application database.
- Process manager: native systemd service, dedicated non-root user.
- Build backend: Hatchling 1.33.0. Python libraries: psutil 7.2.2; Pydantic 2.14.2; Starlette 1.10.0; Uvicorn 0.54.0; pytest 9.2.0; pytest-asyncio 1.4.1; Ruff 0.17.3; Pyright 1.1.414; uv 0.13.6.
- Infrastructure: Docker Compose 5.6.1 CLI; Caddy 2.11.7; Keycloak 26.8.1; PostgreSQL 18.6.

Exact direct versions are pinned in `pyproject.toml`. Generate and commit `uv.lock` on a network-connected machine before reproducible deployment; no lockfile is fabricated in this build because package-index DNS was unavailable.

## MCP interface

Tools: `get_system_metrics`, `get_disk_usage`, `list_processes`, `read_allowed_log`.

Resource: `linux://system/summary`.

Prompt: `health_check`.

The logs tool takes an alias only; the server maps that alias to a fixed systemd unit. The project does not expose arbitrary paths, commands, process termination or service restart.

## Local start

```bash
uv python install 3.15.2
uv lock
uv sync --all-groups
cp .env.example .env
set -a; source .env; set +a
uv run python -m linux_mcp_agent
```

The `.env.example` uses `AUTH_MODE=disabled` for loopback-only development. Do not expose that profile to a LAN. For LAN deployment, configure Keycloak, set `APP_ENV=production` and `AUTH_MODE=keycloak`, install the systemd unit, and expose only Caddy TCP 443.

## Important limitation

Keycloak 26.8.1 documents Resource Indicators support as experimental for the newest MCP protocol revision. The implementation fails closed on wrong/missing audience; the LAN acceptance gate requires integration tests proving `resource` is bound to `aud` and the introspection response contains the expected claims. Do not disable the check to make the demo pass.
