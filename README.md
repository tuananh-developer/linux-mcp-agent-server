# Linux MCP Agent Server

A read-only Linux observability MCP server built with Python and the official MCP Python SDK 2.x. The primary acceptance target is **Ubuntu 24.04 LTS x86_64**.

> **Team-handoff branch status:** this branch is a collaboration baseline, not a deployable release. The MCP core and its architecture documents are retained. Security/Infrastructure and QA/acceptance implementation work has deliberately been returned to the assigned team members. Keep this branch loopback-only; do not expose it to a LAN.

## MCP interface contract

| Primitive | Name | Handoff status |
|---|---|---|
| Tool | `get_system_metrics` | Implemented in the MCP core |
| Tool | `get_disk_usage` | Implemented in the MCP core |
| Tool | `list_processes` | Implemented in the MCP core |
| Tool | `read_allowed_log` | Contract registered; implementation intentionally pending |
| Resource | `linux://system/summary` | Implemented in the MCP core |
| Prompt | `health_check` | Implemented in the MCP core |

The external Agent/MCP Client owns model selection, inference, tool choice, conversation history and provider fallback. This repository does not host an LLM.

## Current implementation boundary

- `system.py` contains the read-only CPU, memory, disk and process collectors.
- `server.py` registers the MCP tools, resource, prompt and operational health route.
- `config.py` contains only the minimal loopback runtime settings required by the core.
- `read_allowed_log` deliberately returns a clear `NOT_IMPLEMENTED` tool error. The journald reader, log-source allowlist and its authorization policy belong to the Security & Infrastructure workstream.
- Keycloak/OAuth implementation, Caddy configuration, Docker Compose infrastructure and the native systemd unit are intentionally absent from this branch. Their target requirements remain documented; they are not proof of a working deployment.

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

CI runs the quality and test suite on Python 3.14.10 and 3.15.2. The existing in-process MCP Client test verifies SDK discovery and core behavior; it does **not** prove deployed Streamable HTTP, OAuth, TLS, LAN reachability or the performance target. Those are explicit member 3 acceptance deliverables.

## Collaboration

Use `team-handoff` as the shared integration baseline. Create feature branches from it and open PRs back into `team-handoff`; do not push directly to `main` or merge this handoff branch into `main` until all workstreams have passed their acceptance gates.
