# Read this first

**Linux MCP Agent Server** is a read-only MCP server for Linux observability. It does not host an LLM and does not implement an Agent runtime. The external Agent/MCP Client owns model selection, inference, tool selection, credentials and provider fallback.

## Locked project baseline (02/11/2026)

- Runtime: Python 3.14 (`.python-version`); CI checks Python 3.14 and 3.15.
- MCP: official Python SDK 2.3.0; Streamable HTTP is the intended transport.
- Linux acceptance target: Ubuntu 24.04 LTS x86_64.
- Intended LAN edge: Caddy 2.11.7 with internal TLS.
- Intended authorization server: Keycloak 26.8.1.
- Intended database: PostgreSQL 18.6 for Keycloak only.
- Intended process manager: native systemd service using a dedicated non-root account.
- Build backend: Hatchling 1.33.0. Python libraries: psutil 7.2.2, Pydantic 2.14.2, Starlette 1.10.0 and Uvicorn 0.54.0. Dev tools: pytest 9.2.0, pytest-asyncio 1.4.1, Ruff 0.17.3, Pyright 1.1.414 and uv 0.13.8.

These are the project's target version decisions, not evidence that every component has been installed or accepted.

## Current integration state

Implemented: all four tools, summary resource, health prompt, validated production configuration, Keycloak introspection and claim checks, log-specific scope enforcement, bounded/redacted journald reads, and infrastructure configuration under `deploy/`.

Unit and in-process contract tests exist. Real Streamable HTTP integration, deployed Keycloak/TLS, second-device LAN checks, systemd verification and per-tool performance reports remain acceptance work. Deployment files are implementation artifacts, not acceptance evidence. Development mode has no authentication and must remain loopback-only.

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
