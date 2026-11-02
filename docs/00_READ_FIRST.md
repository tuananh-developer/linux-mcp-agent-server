# Read this first

**Linux MCP Agent Server** is a read-only MCP server for Linux observability. It does not host an LLM and does not implement an Agent runtime. The external Agent/MCP Client owns model selection, inference, tool selection, credentials and provider fallback.

## Locked project baseline (02/11/2026)

- Runtime: Python 3.15.2; CI checks Python 3.15.2 and 3.14.10.
- MCP: official Python SDK 2.3.0; Streamable HTTP is the intended transport.
- Linux acceptance target: Ubuntu 24.04 LTS x86_64.
- Intended LAN edge: Caddy 2.11.7 with internal TLS.
- Intended authorization server: Keycloak 26.8.1.
- Intended database: PostgreSQL 18.6 for Keycloak only.
- Intended process manager: native systemd service using a dedicated non-root account.
- Build backend: Hatchling 1.33.0. Python libraries: psutil 7.2.2, Pydantic 2.14.2, Starlette 1.10.0 and Uvicorn 0.54.0. Dev tools: pytest 9.2.0, pytest-asyncio 1.4.1, Ruff 0.17.3, Pyright 1.1.414 and uv 0.13.6.

These are the project's target version decisions, not evidence that every component has been installed or accepted.

## Current state of the team-handoff branch

Implemented and retained:
- MCP core: `get_system_metrics`, `get_disk_usage`, `list_processes`.
- MCP Resource: `linux://system/summary`.
- MCP Prompt: `health_check`.
- Registered contract for `read_allowed_log`; the handler deliberately returns `NOT_IMPLEMENTED` until its owner implements the journald reader and authorization.
- Loopback-only application settings and in-process official MCP Client contract tests.

Intentionally returned to the Security & Infrastructure workstream:
- Keycloak token introspection, OAuth claim and scope validation.
- Journald alias configuration and bounded/redacted log reader.
- Keycloak/PostgreSQL/Caddy Docker Compose infrastructure.
- Caddy route and TLS configuration.
- Native systemd service, production environment template and deployment procedure.

Intentionally returned to the QA / Integration workstream:
- Real Streamable HTTP client integration.
- Keycloak positive/negative authorization tests.
- Caddy/TLS and second-LAN-device acceptance.
- systemd privilege/deployment verification.
- p95 performance benchmarks, report and acceptance evidence.

**Important:** this branch has no working OAuth protection or LAN deployment. Do not expose the application outside loopback. The documents under `docs/07`–`docs/09` and `deploy/*/README.md` describe the target design and acceptance criteria only.

## MCP interface contract

Tools: `get_system_metrics`, `get_disk_usage`, `list_processes`, `read_allowed_log`.

Resource: `linux://system/summary`.

Prompt: `health_check`.

## Local start

```bash
uv sync --all-groups
cp .env.example .env
set -a; source .env; set +a
uv run python -m linux_mcp_agent
```

Default bind: `127.0.0.1:3000`. Keep it loopback-only.
