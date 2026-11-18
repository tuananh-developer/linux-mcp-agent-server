# Linux MCP Agent Server

A read-only Linux observability server that exposes host telemetry through the Model Context Protocol (MCP). The primary deployment and acceptance target is **Ubuntu 24.04 LTS x86_64**.

The repository implements an MCP server only. It does not host an LLM or an Agent runtime. The external Agent/MCP Client owns model selection, inference, tool selection, conversation history and provider fallback.

## MCP capabilities

| Type | Name | Purpose |
|---|---|---|
| Tool | `get_system_metrics` | Timestamped CPU, memory, load average and uptime |
| Tool | `get_disk_usage` | Filesystem capacity for administrator-allowlisted mount points |
| Tool | `list_processes` | Bounded process snapshot without command lines or environment values |
| Tool | `read_allowed_log` | Bounded, redacted journald entries from configured service aliases |
| Resource | `linux://system/summary` | High-level JSON host summary |
| Prompt | `health_check` | Safe, read-only host health-check guidance |

The server is read-only. It does not expose arbitrary shell execution, arbitrary file reads, process termination, service restart or file mutation.

## Architecture

- **MCP application:** Python, official MCP Python SDK 2.3.0, Streamable HTTP at `/mcp`; runs natively under systemd and binds to `127.0.0.1:3000`.
- **Identity:** Keycloak 26.8.1 issues OAuth access tokens. The MCP application is a resource server and validates tokens using RFC 7662 introspection, exact issuer, expiry, resource/audience and scopes.
- **TLS ingress:** Caddy 2.11.7 terminates internal TLS and exposes only the approved MCP and OIDC routes to the LAN.
- **Persistence:** PostgreSQL 18.6 stores Keycloak identity/configuration data only. It is **not an application database**; the MCP telemetry service does not persist metrics.
- **Containers:** Docker Compose runs PostgreSQL, Keycloak and the optional LAN-facing Caddy service. The MCP process itself is not containerized.

## Local development

Use Python 3.15.2 (CI also checks Python 3.14.10) and uv 0.13.8.

```bash
uv python install 3.15.2
uv sync --all-groups
cp .env.example .env
set -a
source .env
set +a
uv run linux-mcp-agent
```

The development environment defaults to `AUTH_MODE=disabled` and loopback binding. It is for same-host development only. Do not expose this mode to a LAN or public network.

## Project requirements and traceability

The SRS is the canonical requirements baseline. The full FR/NFR mapping from implementation and automated tests to live acceptance evidence is in [docs/11_requirements_traceability.md](docs/11_requirements_traceability.md).

## Quality checks

```bash
uv run ruff check .
uv run pyright
uv run pytest
```

The test suite includes unit tests, an in-process MCP SDK contract test and an actual TCP/Streamable HTTP integration test. These automated tests do not replace live Keycloak, TLS trust, second-device LAN, systemd privilege or performance acceptance on Ubuntu 24.04.

## Infrastructure deployment

Follow [the Ubuntu 24.04 deployment guide](docs/09_ubuntu2404_deployment.md). The intended sequence is PostgreSQL and Keycloak first, then the authenticated native MCP service, and Caddy only after local token validation succeeds.

Keep the firewall restrictive: only the intended HTTPS ingress (TCP 443) should be reachable from the selected demo network. Do not publish PostgreSQL (5432), Keycloak (8080) or MCP (3000) to the LAN.

## Performance benchmark

The benchmark runner uses the official MCP Python Client over Streamable HTTP. It reports p50/p95/p99, success/error counts and host/runtime metadata without recording access tokens or tool output.

```bash
MCP_BENCHMARK_URL=https://mcp.home.arpa/mcp \
MCP_BENCHMARK_ACCESS_TOKEN='<read token>' \
MCP_BENCHMARK_LOG_ALIAS=ssh \
uv run python scripts/benchmark_mcp.py --iterations 100
```

Use a valid bearer token from a protected secret source. Set `MCP_BENCHMARK_LOG_ALIAS` only when the token includes `mcp.logs.read`. Benchmark evidence must be produced on the designated Ubuntu 24.04 host and recorded under `reports/acceptance/`; no benchmark result is assumed by this repository.

## Integration status

The `integration/finalize-ubuntu2404` branch consolidates the Security & Infrastructure implementation with the Technical Lead workstream definition, adds defensive fixes and automated HTTP/performance tooling. It is a release-readiness candidate, **not a claim of completed live acceptance**.

Open acceptance gates include real Keycloak token flows, trusted Caddy TLS from a second LAN client, systemd identity/sandbox inspection, PostgreSQL volume persistence on the target host and measured per-tool p95 latency. Record results and limitations before declaring the project accepted.
