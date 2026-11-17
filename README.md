# Linux MCP Agent Server

A read-only Linux observability MCP server built with Python and the official MCP Python SDK 2.x. The primary acceptance target is **Ubuntu 24.04 LTS x86_64**.

> **Integration status:** core telemetry, journald, Keycloak introspection and deployment configurations are implemented. Real HTTP/OAuth/TLS/LAN, systemd and performance acceptance evidence is still pending. Keep development mode loopback-only.

## MCP interface contract

| Primitive | Name | Handoff status |
|---|---|---|
| Tool | `get_system_metrics` | Implemented in the MCP core |
| Tool | `get_disk_usage` | Implemented in the MCP core |
| Tool | `list_processes` | Implemented in the MCP core |
| Tool | `read_allowed_log` | Implemented; deployment acceptance pending |
| Resource | `linux://system/summary` | Implemented in the MCP core |
| Prompt | `health_check` | Implemented in the MCP core |

The external Agent/MCP Client owns model selection, inference, tool choice, conversation history and provider fallback. This repository does not host an LLM.

## Current implementation boundary

- `system.py` collects read-only CPU, memory, disk and process metrics.
- `server.py` registers four tools, the summary resource, health prompt and health route.
- `config.py` validates loopback binding and production authentication settings.
- `auth.py` and `auth_claims.py` implement Keycloak introspection and claim validation.
- `log_reader.py` implements alias-only, bounded and redacted journald reads with a separate log scope.
- `deploy/` contains Compose, Caddy, Keycloak and systemd configurations. Their presence does not prove a successful deployment.

## Architecture and requirements

Start with:

- `docs/00_READ_FIRST.md`
- `docs/01_software_requirements_specification.md`
- `docs/02_project_charter_and_scope.md`
- `docs/03_architecture_and_design.md`
- `docs/04_ooad_analysis_and_uml.md`
- `docs/05_mcp_interface_contracts.md`
- `docs/10_team_workstream_handoff.md`

Security and deployment design references:

- `docs/07_security_threat_model.md`
- `docs/08_authorization_tls_design.md`
- `docs/09_ubuntu2404_deployment.md`
- `deploy/keycloak/README.md`
- `deploy/caddy/README.md`
- `deploy/compose/README.md`
- `deploy/systemd/README.md`

These documents describe requirements and intended acceptance behavior. A member must implement and validate the corresponding infrastructure before it can be considered complete.

## Local development

The current app configuration is intentionally loopback-only:

```bash
uv sync --all-groups
cp .env.example .env
set -a; source .env; set +a
uv run python -m linux_mcp_agent
```

The server binds to `127.0.0.1:3000` by default. The local mode has no OAuth protection and is for development on the same host only. Never change the bind address to `0.0.0.0` to bypass the missing infrastructure work.

## Quality checks

```bash
uv run ruff check .
uv run pyright
uv run pytest
```

CI runs the quality and test suite on Python 3.14 and 3.15. The existing in-process MCP Client test verifies SDK discovery and core behavior; it does **not** prove deployed Streamable HTTP, OAuth, TLS, LAN reachability or the performance target. Those are explicit member 3 acceptance deliverables.

## Collaboration

Use `team-handoff` as the shared integration baseline. Create feature branches from it and open PRs back into `team-handoff`; do not push directly to `main` or merge this handoff branch into `main` until all workstreams have passed their acceptance gates.
