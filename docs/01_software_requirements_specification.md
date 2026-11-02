# Software Requirements Specification

**Project:** Linux MCP Agent Server  
**Document ID:** LMAS-SRS-001  
**Version:** 1.0  
**Status:** Baseline for implementation and acceptance  
**Acceptance platform:** Ubuntu 24.04 LTS x86_64

## 1. Introduction

### 1.1 Purpose

This document defines the functional and non-functional requirements for a read-only Linux observability server that exposes operating-system information to an external Agent/MCP Client through the Model Context Protocol (MCP). It is the requirements baseline for implementation, verification and demonstration.

### 1.2 Product scope

The product is a Python MCP Server using the official MCP Python SDK. It reads selected Linux telemetry and journald entries, applies server-side allowlists and authorization, and returns structured MCP results. It does not host an LLM or implement an Agent runtime.

### 1.3 Definitions

- **MCP:** Model Context Protocol, used by the Agent/MCP Client to discover and invoke server capabilities.
- **MCP Tool:** An invokable server operation exposed through MCP.
- **MCP Resource:** Readable contextual data exposed through a stable URI.
- **MCP Prompt:** A reusable prompt template exposed by the server.
- **Resource server:** The service that validates access tokens and protects a resource; in this project, the MCP application.
- **Agent/MCP Client:** An external application that owns model inference and communicates with this MCP Server.
- **Allowlist:** A server-controlled list of resources that callers are permitted to request.

## 2. Overall description

### 2.1 Product perspective

The system consists of an external Agent/MCP Client, a TLS reverse proxy, the MCP application, an OAuth authorization server and the Linux host. The MCP application is a resource server and does not issue tokens. PostgreSQL is used only as Keycloak persistence.

### 2.2 User classes

- **End user:** Requests a system health overview through an external Agent.
- **Agent/MCP Client:** Discovers tools/resources/prompts and invokes permitted operations using an OAuth access token.
- **System administrator:** Configures allowed disk paths, log aliases, secrets, service identity, network exposure and authorization settings.
- **Developer/tester:** Runs unit, contract, integration, security and performance tests.

### 2.3 Operating environment

- Ubuntu 24.04 LTS x86_64 is the primary acceptance target.
- Python 3.14 and 3.15 are the CI compatibility targets; Python 3.15.2 is the pinned development runtime.
- The MCP application binds to loopback and is exposed to the LAN only through Caddy HTTPS.
- Keycloak and PostgreSQL provide authorization and identity persistence; systemd supervises the native MCP process.

### 2.4 Design constraints

- The server is read-only.
- Client input must not become a shell command, executable path, filesystem path or systemd unit.
- Disk paths and log aliases are administrator-controlled.
- Journal output and other tool results are untrusted data.
- LLM inference, provider credentials and fallback policy remain outside this repository.

### 2.5 Assumptions and dependencies

- The target Linux host provides systemd/journald and the configured Linux telemetry interfaces.
- Keycloak is configured to issue resource-bound access tokens with the required audience and scopes.
- LAN clients trust the Caddy internal CA certificate.
- The administrator configures existing disk mount points and valid systemd unit aliases before enabling the corresponding tools.

## 3. Functional requirements

| ID | Requirement |
|---|---|
| FR-001 | The server shall expose MCP over Streamable HTTP at \`/mcp\`. |
| FR-002 | The server shall provide \`get_system_metrics\`, returning timestamped CPU, logical core count, memory, load average, uptime and status. |
| FR-003 | The server shall provide \`get_disk_usage\`, returning capacity metrics only for exact administrator-allowlisted mount points. |
| FR-004 | The server shall provide \`list_processes\`, with a limit from 1 to 100, CPU or memory sorting, and an optional bounded name filter. Returned process fields shall be limited to PID, name, CPU%, memory%, RSS bytes and status. |
| FR-005 | The process reader shall detect process exit or PID reuse between samples and shall not combine measurements from different process identities. |
| FR-006 | The server shall provide \`read_allowed_log\`, accepting an alias and a bounded line count only. The alias shall resolve to a configured systemd unit. |
| FR-007 | Journal reads shall use a fixed server-controlled \`journalctl\` executable and argument list, disable shell interpretation, enforce time/output limits and redact common secret patterns. |
| FR-008 | The server shall expose a JSON system summary at \`linux://system/summary\`. |
| FR-009 | The server shall expose a \`health_check\` prompt with a constrained focus argument. |
| FR-010 | The server shall expose \`/healthz\` as a separate operational health endpoint. |
| FR-011 | The server shall require the configured base scope for MCP access and the additional log scope before reading journald. |
| FR-012 | The server shall return structured, bounded results and safe errors without exposing tokens, client secrets, process command lines or process environment values. |

## 4. External interface requirements

### 4.1 MCP interface

The server shall expose four tools: \`get_system_metrics\`, \`get_disk_usage\`, \`list_processes\` and \`read_allowed_log\`; one resource: \`linux://system/summary\`; and one prompt: \`health_check\`.

### 4.2 Authentication interface

In production mode, the MCP resource server shall introspect bearer access tokens with Keycloak and enforce active status, exact issuer, expiry, resource/audience and configured scopes. The server shall fail closed when introspection is unavailable or claims are missing/invalid.

### 4.3 Host interface

The application shall read host metrics through supported Linux interfaces and psutil. Journal access shall use only administrator-configured aliases. The application shall not expose arbitrary host commands or mutation operations.

## 5. Non-functional requirements

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

## 6. Data and privacy requirements

- Process results shall not include command-line arguments, environment variables or usernames.
- The system summary shall not include tokens, secrets, raw logs or process command lines.
- The server shall not forward telemetry or journal output to an LLM or external provider.
- Application logs shall not contain bearer tokens or client secrets.

## 7. Verification and acceptance

| Requirement group | Verification method | Acceptance evidence |
|---|---|---|
| FR-001, FR-008, FR-009 | MCP protocol/contract test with a standards-compliant client | Initialize, list tools/resources/prompts, read resource and get prompt |
| FR-002 to FR-007, FR-010 | Unit and component tests | Test output and representative runtime results |
| FR-011 and NFR-SEC-003 | OAuth positive/negative integration tests | Valid token succeeds; invalid token, wrong audience and missing scopes fail |
| NFR-SEC-001, 002, 004, 005 | Code review and host inspection | No mutation tools, loopback binding, protected secrets, bounded log output |
| NFR-PRF-001, 002 | Repeated benchmark on acceptance host | Per-tool p50/p95/max with host and test conditions |
| NFR-REL-001 | GitHub Actions | Successful CI run for Python 3.14 and 3.15 |
| NFR-DEP-001 | Deployment verification | systemd service identity, listener addresses and second-device HTTPS test |

The project shall not be marked accepted until all acceptance evidence is recorded. A green unit-test/CI run alone does not prove Keycloak, TLS, LAN deployment or end-to-end integration.

## 8. Traceability

The implementation mapping is:

- FR-001, FR-008, FR-009, FR-010: \`src/linux_mcp_agent/server.py\`.
- FR-002, FR-003, FR-004, FR-005: \`src/linux_mcp_agent/system.py\`.
- FR-006, FR-007: \`src/linux_mcp_agent/log_reader.py\`.
- FR-011: \`src/linux_mcp_agent/auth.py\`, \`src/linux_mcp_agent/auth_claims.py\` and the log-scope check in \`server.py\`.
- Runtime constraints: \`src/linux_mcp_agent/config.py\`.
- Automated tests: \`tests/\`; deployment evidence is collected on the Ubuntu acceptance host.
