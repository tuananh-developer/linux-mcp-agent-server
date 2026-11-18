# Read this first

**Linux MCP Agent Server** is a read-only Linux observability MCP server. Clients can connect to MCP directly, or use the browser assistant at `http://localhost:3002/`. See [the README](../README.md) for model configuration and data handling.

## Locked project baseline

- Runtime: Python 3.15.2; CI checks the Python 3.14 and 3.15 release lines (uv resolves the available patch release; the latest observed CI runtimes were 3.14.10 and 3.15.2).
- MCP: official Python SDK 2.3.0; deployed transport is Streamable HTTP.
- Linux acceptance target: Ubuntu 24.04 LTS x86_64.
- Application endpoint: `/mcp`, backend bound to `127.0.0.1:3002`.
- LAN edge: Caddy 2.11.7 with internal TLS.
- Authorization server: Keycloak 26.8.1.
- Database: PostgreSQL 18.6 for Keycloak persistence only; no application database.
- Process manager: native systemd service under a dedicated non-root account.
- Python runtime dependencies: MCP 2.3.0, psutil 7.2.2, Pydantic 2.14.2, Starlette 1.10.0 and Uvicorn 0.54.0.
- Development tooling is pinned in `pyproject.toml` and `uv.lock`; the CI runtime uses uv 0.13.8.

Pinned versions describe the reproducible project baseline. They are not proof that the target Ubuntu host has been deployed or accepted.

## Integration candidate contents

The `integration/finalize-ubuntu2404` branch brings together:

- MCP Core: four Tools, one Resource, one Prompt and read-only Linux telemetry.
- OAuth/Keycloak token introspection and scope enforcement.
- Bounded journald access through administrator-configured aliases.
- Caddy route/TLS configuration, PostgreSQL/Keycloak/Caddy Compose model and native systemd unit.
- Unit tests, in-process MCP contract coverage and an actual Streamable HTTP client test over TCP.
- A benchmark runner that emits per-tool latency distributions and host metadata.
- Technical Lead responsibilities, updated architecture/design documentation and acceptance gates.
- A requirement-by-requirement FR/NFR traceability matrix: [docs/11_requirements_traceability.md](11_requirements_traceability.md).

The branch also includes fixes for PostgreSQL 18 volume layout, Keycloak readiness checks, audience/resource configuration consistency, malformed token timestamps, invalid journal timestamps and measured process sampling duration.

## Safety boundary

- The MCP service binds to loopback; Caddy is the only intended LAN entry point.
- OAuth validation fails closed. Production mode requires Keycloak authentication.
- Log reads accept aliases only; systemd unit names and journalctl arguments are server-controlled.
- Process command lines, environment variables, usernames, tokens and client secrets are not returned.
- No arbitrary shell, mutation, process kill or service restart functionality is exposed.

## MCP interface

Tools: `get_system_metrics`, `get_disk_usage`, `list_processes`, `read_allowed_log`.

Resource: `linux://system/summary`.

Prompt: `health_check`.

Base scope: `mcp.read`. Additional journal scope: `mcp.logs.read`.

## Validation boundary

A green CI run proves only the automated checks executed by CI. Final acceptance still requires evidence collected on Ubuntu 24.04 LTS: Keycloak positive/negative token flows, trusted Caddy TLS from a second LAN device, loopback-only socket exposure, systemd non-root/sandbox inspection, PostgreSQL volume persistence and repeatable per-tool p95 measurements.

Do not claim these host-level checks have passed until the raw commands, outputs, environment details and limitations are recorded under `reports/acceptance/`.
