# Project charter and scope

## Objective

Deliver a secure, read-only Linux observability MCP server that exposes selected host information to an external Agent/MCP Client through the Model Context Protocol.

## System boundary

- **External Agent/MCP Client:** owns model selection, inference, tool choice, conversation history and provider fallback.
- **MCP application:** owns protocol handling, input validation, OAuth resource-server enforcement and read-only telemetry collection.
- **Keycloak:** owns identity and access-token issuance; the MCP application introspects tokens and does not issue them.
- **Caddy:** owns LAN-facing TLS termination and reverse-proxy route allowlisting.
- **PostgreSQL:** stores Keycloak identity/configuration data only. It is not an application database and is not used to persist host metrics.

## In scope

- Official MCP Python SDK 2.x and Streamable HTTP at `/mcp`.
- Four MCP Tools, one MCP Resource and one MCP Prompt.
- Linux CPU, memory, load, uptime, allowlisted disk capacity, bounded process information and allowlisted journald entries.
- Keycloak OAuth2/OIDC resource-server validation with exact issuer, expiry, resource/audience and least-privilege scopes.
- Caddy internal TLS, PostgreSQL for Keycloak persistence, Docker Compose for supporting infrastructure, and a native systemd service for the MCP application.
- Unit, MCP contract, actual HTTP integration, security, deployment and performance verification.
- Ubuntu 24.04 LTS x86_64 as the primary acceptance environment.

## Out of scope

- LLM hosting, model inference, Agent orchestration and provider fallback inside this repository.
- Arbitrary shell execution, arbitrary path access, file writes/deletes, process termination or service restart.
- A user-facing dashboard, application database, public multi-tenant service or cloud deployment.
- Claims of distribution portability without platform-specific tests.

## Canonical requirements

The Software Requirements Specification (`docs/01_software_requirements_specification.md`) is the single source of truth for requirement identifiers and normative wording. Other documents must reference these IDs rather than define competing copies. The module/test/live-evidence mapping is maintained in [docs/11_requirements_traceability.md](11_requirements_traceability.md).

| Requirement group | Canonical IDs | Primary implementation |
|---|---|---|
| MCP transport, Resource, Prompt and health route | FR-001, FR-008, FR-009, FR-010 | `server.py` |
| System metrics and disk usage | FR-002, FR-003 | `system.py` |
| Process listing and PID-reuse protection | FR-004, FR-005 | `system.py` |
| Journald allowlist, bounded execution and redaction | FR-006, FR-007 | `log_reader.py` |
| Base scope and log-specific scope | FR-011 | `auth.py`, `auth_claims.py`, `server.py` |
| Safe structured output and errors | FR-012 | MCP handlers and telemetry/log readers |
| Security, performance, reliability and deployment | NFR-SEC-001..005, NFR-PRF-001..002, NFR-REL-001, NFR-DEP-001, NFR-MNT-001 | Application, infrastructure and acceptance evidence |

## Architecture decisions

- Python and the official MCP SDK are retained; a language rewrite is not part of this release.
- MCP is the application protocol boundary. The server does not embed an LLM.
- The MCP service runs natively under systemd and listens only on loopback.
- Docker Compose runs only the supporting identity/TLS services: PostgreSQL, Keycloak and Caddy.
- PostgreSQL is exclusively Keycloak persistence; metrics and process snapshots are read from the Linux host and are not persisted by the application.
- The read-only security boundary takes priority over feature breadth.

## Acceptance gates

1. Ruff, strict Pyright and pytest pass on every supported Python CI matrix entry.
2. A standards-compliant MCP Client successfully connects over actual Streamable HTTP and discovers/calls all required capabilities.
3. Positive and negative OAuth checks prove active state, issuer, expiry, audience/resource, base scope and log-specific scope enforcement.
4. From a second LAN device, a valid client completes an authenticated HTTPS MCP session using a trusted Caddy CA certificate.
5. PostgreSQL data persists across a controlled container recreation; no database port is exposed to the LAN.
6. MCP and Keycloak bind to loopback, and the systemd process runs as a dedicated non-root user with reviewed sandbox and journal privileges.
7. Per-tool benchmark evidence records p50/p95/p99 and host conditions; p95 target is at or below 2 seconds on the designated Ubuntu 24.04 host, excluding external LLM inference.
8. Evidence, commands, environment details, failures and limitations are recorded before the project is declared accepted.

## Definition of done

A committed implementation or a green CI badge is not sufficient by itself. Each workstream must provide reproducible positive/negative tests and explain known limitations. Live host/network checks must be recorded rather than inferred.
