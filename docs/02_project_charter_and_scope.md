# Project charter and scope

## Objective

Build and configure a secure, read-only Linux MCP server that exposes system observability tools to an external Agent/MCP Client through the Model Context Protocol.

## In scope

- Official MCP Python SDK v2, Streamable HTTP endpoint at \`/mcp\`.
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

| ID | Requirement | Verification |
|---|---|---|
| FR-001 | The server shall expose MCP over Streamable HTTP at \`/mcp\`. | MCP client initialize and discovery test |
| FR-002 | The server shall expose CPU, memory, load average and uptime through \`get_system_metrics\`. | Unit test and live host check |
| FR-003 | The server shall return disk usage only for administrator-allowlisted absolute paths. | Allowlist positive/negative tests |
| FR-004 | The server shall return a bounded process snapshot with PID, name, CPU%, RAM% and RSS bytes, without command lines or environment values. | Process reader unit tests |
| FR-005 | The server shall read only configured journald aliases, with bounded lines, output bytes, execution time and best-effort secret redaction. | Log reader security tests |
| FR-006 | The server shall expose a JSON system summary at \`linux://system/summary\`. | MCP resource discovery/read test |
| FR-007 | The server shall expose a \`health_check\` prompt with a constrained focus argument. | MCP prompt discovery/get test |
| FR-008 | The server shall require the configured base OAuth scope for MCP access and an additional log scope for journal reads. | Authorization unit and integration tests |
| FR-009 | The server shall expose a separate operational health endpoint at \`/healthz\`. | HTTP health check |

## Non-functional requirements

| ID | Requirement | Verification |
|---|---|---|
| NFR-SEC-001 | The application shall remain read-only and shall not expose arbitrary shell execution or destructive host operations. | API review and security tests |
| NFR-SEC-002 | The MCP process shall bind to loopback; LAN access shall pass through the TLS reverse proxy. | Configuration and socket inspection |
| NFR-SEC-003 | Invalid, expired, wrong-issuer, wrong-audience or insufficient-scope tokens shall fail closed. | OAuth negative integration tests |
| NFR-SEC-004 | Log access shall use fixed server-owned executable arguments with \`shell=False\`. | Code review and command-boundary tests |
| NFR-PRF-001 | Each MCP tool shall achieve p95 response time at or below 2 seconds on the designated acceptance host, excluding external LLM inference. | Repeated benchmark with recorded host details |
| NFR-PRF-002 | Process sampling shall use a bounded sample window and journal reads shall enforce configured time/output limits. | Unit tests and runtime measurements |
| NFR-REL-001 | The project shall pass Ruff, strict Pyright and pytest in CI on supported Python versions. | GitHub Actions |
| NFR-DEP-001 | The acceptance deployment shall run on Ubuntu 24.04 LTS x86_64 using a dedicated non-root systemd account. | Deployment checklist and system inspection |
| NFR-MNT-001 | Runtime configuration shall be environment-driven; secrets shall not be committed to source control. | Configuration review and secret scan |

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
