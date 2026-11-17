# Project charter and scope

## Objective

Build and configure a secure, read-only Linux MCP server that exposes system observability tools to an external Agent/MCP Client through the Model Context Protocol.

## In scope

- Official MCP Python SDK v2, Streamable HTTP endpoint at `/mcp`.
- Linux CPU/RAM, allowlisted filesystem usage, bounded process list, allowlisted real systemd journal access.
- Four MCP Tools, one MCP Resource and one MCP Prompt.
- OAuth2/OIDC resource-server validation using Keycloak, exact issuer and resource/audience binding, and least-privilege scopes.
- Caddy HTTPS reverse proxy, PostgreSQL for Keycloak only, Docker Compose for infrastructure, and native systemd service for the MCP process.
- Unit, protocol-contract, integration, security and performance test plans.
- Ubuntu 24.04 LTS x86_64 as the primary acceptance environment; group of three.

## Out of scope

- LLM hosting, model inference, LangChain orchestration and provider fallback inside this repository.
- Arbitrary command execution, file writes/deletes, killing processes, or restarting services.
- Public multi-tenant service, dashboard, application database, or cloud deployment.
- Claiming distribution portability without tests.

## Functional requirements

Requirement IDs and wording follow `docs/01_software_requirements_specification.md`, the authoritative acceptance baseline.

| ID | Requirement |
|---|---|
| FR-001 | The server shall expose MCP over Streamable HTTP at `/mcp`. |
| FR-002 | The server shall provide `get_system_metrics`, returning timestamped CPU, logical core count, memory, load average, uptime and status. |
| FR-003 | The server shall provide `get_disk_usage`, returning capacity metrics only for exact administrator-allowlisted mount points. |
| FR-004 | The server shall provide `list_processes`, with a limit from 1 to 100, CPU or memory sorting, and an optional bounded name filter. Returned process fields shall be limited to PID, name, CPU%, memory%, RSS bytes and status. |
| FR-005 | The process reader shall detect process exit or PID reuse between samples and shall not combine measurements from different process identities. |
| FR-006 | The server shall provide `read_allowed_log`, accepting an alias and a bounded line count only. The alias shall resolve to a configured systemd unit. |
| FR-007 | Journal reads shall use a fixed server-controlled `journalctl` executable and argument list, disable shell interpretation, enforce time/output limits and redact common secret patterns. |
| FR-008 | The server shall expose a JSON system summary at `linux://system/summary`. |
| FR-009 | The server shall expose a `health_check` prompt with a constrained focus argument. |
| FR-010 | The server shall expose `/healthz` as a separate operational health endpoint. |
| FR-011 | The server shall require the configured base scope for MCP access and the additional log scope before reading journald. |
| FR-012 | The server shall return structured, bounded results and safe errors without exposing tokens, client secrets, process command lines or process environment values. |

## Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-SEC-001 | The product shall remain read-only and shall not expose arbitrary shell execution, file mutation, process termination or service restart. |
| NFR-SEC-002 | The application shall bind to loopback; Caddy shall be the only LAN-facing application entry point. |
| NFR-SEC-003 | Invalid, expired, wrong-issuer, wrong-audience/resource or insufficient-scope access tokens shall fail closed. |
| NFR-SEC-004 | Secrets shall be supplied through protected runtime configuration and shall not be committed to the repository. |
| NFR-SEC-005 | Journal output shall be treated as untrusted content and shall be bounded and redacted on a best-effort basis. |
| NFR-PRF-001 | Each MCP tool shall achieve p95 response time at or below 2 seconds on the designated acceptance host, excluding external LLM inference. |
| NFR-PRF-002 | Process sampling shall be bounded to at most 1 second; journal reads shall enforce configured time and byte limits. |
| NFR-REL-001 | Ruff, strict Pyright and pytest shall pass in CI for every supported Python matrix entry. |
| NFR-DEP-001 | The primary acceptance deployment shall use Ubuntu 24.04 LTS x86_64 and a dedicated non-root systemd account. |
| NFR-MNT-001 | Runtime configuration shall be environment-driven and documented; production mode shall require authenticated access. |

## System boundary and responsibilities

- The external Agent/MCP Client owns model selection, inference, tool choice, conversation history and provider fallback.
- The MCP Server owns MCP protocol handling, authorization enforcement, input validation and read-only Linux data collection.
- Keycloak owns token issuance; the MCP Server acts only as a resource server.
- Caddy owns LAN TLS termination and route exposure.
- PostgreSQL stores Keycloak data only; it is not an application database.

## Acceptance gates

1. Unit tests and quality tools pass on every supported Python matrix entry.
2. A standards-compliant MCP Client initializes the server and discovers all four tools, the resource and the prompt over Streamable HTTP.
3. Positive and negative OAuth integration tests prove issuer, expiry, audience/resource, base scope and log-specific scope enforcement.
4. A second LAN device connects over trusted HTTPS; Caddy and Keycloak administration routes remain restricted.
5. systemd runs as a dedicated non-root user; journal group access and its residual privilege are explicitly reviewed.
6. A repeatable benchmark records p95 at or below 2 seconds for each tool on the designated acceptance host.
7. Deployment evidence, test output and known limitations are recorded before the project is marked accepted.

## Scope decisions

- Linux acceptance target is Ubuntu 24.04 LTS. Fedora may be used for development, but it is not the acceptance environment unless the team and lecturer formally change the baseline.
- No LLM runtime is embedded in this repository. Agent/model behavior is tested at the external client boundary.
- The read-only boundary takes priority over feature breadth. Do not add arbitrary command execution to improve the demo.
