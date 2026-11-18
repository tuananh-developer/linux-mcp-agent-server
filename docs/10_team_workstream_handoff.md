# Team workstream handoff

**Shared integration base:** `team-handoff` · **Team size:** 3

This document defines the three workstreams and their ownership boundaries. The `integration/finalize-ubuntu2404` candidate combines the Technical Lead scope with the Security & Infrastructure implementation. Workstream 3 owns independent integration, deployment and performance acceptance on the target Ubuntu host. Keep feature changes PR-based; do not merge to `main` until all acceptance gates have recorded evidence.

## Current workstream status — 2026-11-18

- **WS1:** the architecture, SRS, charter, OOAD, MCP contract, core telemetry, ADRs, integration candidate and FR/NFR traceability are maintained on `integration/finalize-ubuntu2404`. Fresh CI on the synchronized candidate and PR review remain required before calling the integration candidate ready.
- **WS2:** security/infrastructure code is complete and integrated through PRs #4, #13 and #15 on `team-handoff`. This is a code-completion statement only; it does not claim that the Ubuntu deployment or host-level checks have passed.
- **WS3:** automated security/acceptance scaffolding is present. Live OAuth, HTTPS/LAN, systemd, PostgreSQL persistence and four-tool performance evidence remain outstanding until recorded under `reports/acceptance/`.

The detailed status and evidence mapping is maintained in [docs/11_requirements_traceability.md](11_requirements_traceability.md).

## Workstream 1 — Technical Leadership, Architecture and MCP Core

**Owner:** Group leader (Member 1).  
**Role:** Technical Lead / Architecture & MCP Core Owner.

### Mission

Own the system-level technical direction and the stable MCP Core. Keep requirements, architecture, public interfaces and implementation aligned; review and integrate the other workstreams without taking over their implementation or independent acceptance responsibilities.

### Responsibilities

1. **Requirements and scope governance**
   - Own the Project Charter, scope, Software Requirements Specification (SRS), functional/non-functional requirements and requirement traceability.
   - Keep one authoritative set of FR/NFR identifiers. Ensure the Architecture, OOAD/UML, MCP contract, tests and acceptance evidence use those same identifiers.
   - Review requirement changes for scope, feasibility, security impact and compatibility. Record approved changes and their rationale.

2. **System architecture and technical decisions**
   - Own the high-level architecture, component boundaries, deployment topology, data flows, trust boundaries and UML/sequence diagrams.
   - Define module responsibilities and dependency direction. Keep protocol composition, Linux telemetry, configuration, authentication and infrastructure concerns separated.
   - Record material technical decisions in concise Architecture Decision Records (ADRs), including context, alternatives, decision and consequences. Examples include the Python runtime, official MCP SDK, read-only boundary and transport/deployment choices.
   - Maintain the supported runtime, SDK and dependency baseline across the design documents. Do not introduce a new language, framework or service without a documented need and measurable benefit.

3. **MCP Core and public interface ownership**
   - Own MCP server composition in `src/linux_mcp_agent/server.py` and the public interface contract in `docs/05_mcp_interface_contracts.md`.
   - Maintain the four-tool contract (`get_system_metrics`, `get_disk_usage`, `list_processes`, `read_allowed_log`), the `linux://system/summary` Resource and the `health_check` Prompt. The implementation of authentication and journald access remains with Workstream 2.
   - Define and review tool names, descriptions, input schemas, validation boundaries, result shapes, error semantics, Resource URI and Prompt arguments before implementation changes are integrated.
   - Use MCP metadata such as read-only Tool annotations where supported and appropriate. Treat annotations as client-facing hints only; they never replace server-side authorization, validation or allowlists.
   - Preserve backward compatibility. Any breaking contract change requires an explicit design decision, updated documentation, tests and approval before integration.
   - Keep MCP transport/session lifecycle and ASGI composition correct, including startup/shutdown behavior and the separation of operational health checks from MCP routes.

4. **Linux telemetry core**
   - Own the read-only CPU, memory, load, uptime, disk and process collectors in `src/linux_mcp_agent/system.py`.
   - Ensure metrics have documented semantics, timestamps, units and bounded execution. In particular, document how process CPU percentage is calculated and distinguish configured sampling delay from actual elapsed sampling time.
   - Handle process exit, PID reuse, access-denied processes, missing mount points and platform/runtime edge cases without returning misleading measurements.
   - Keep the core telemetry layer independent of MCP, Keycloak and deployment infrastructure. It must not expose process command lines, environment variables, usernames or destructive host operations.

5. **Core quality and maintainability**
   - Maintain focused unit and MCP contract tests for the code owned by Workstream 1.
   - Keep Ruff, strict Pyright and pytest expectations aligned with the supported Python matrix.
   - Review module boundaries, typing, error handling, naming, documentation and test coverage when accepting changes that affect the core contract.
   - Avoid unnecessary abstractions or dependencies. Add complexity only when it solves a documented requirement or a demonstrated engineering problem.

6. **Technical review and integration**
   - Review incoming Workstream 2 and Workstream 3 PRs for architecture fit, contract compatibility, security boundaries, test evidence and maintainability.
   - Resolve interface conflicts and coordinate integration on the shared `team-handoff` branch. Do not bypass the PR workflow or merge feature work directly into `main`.
   - Require each workstream owner to provide implementation details, commands, actual test results, known limitations and evidence appropriate to their scope.
   - Run or coordinate cross-workstream regression checks after integration. Do not claim deployment, OAuth, LAN or performance acceptance solely from unit tests or a green CI run.
   - Maintain an integration/acceptance status summary and identify blockers, owners and follow-up actions.

### Workstream 1 deliverables

- Approved Project Charter and SRS with consistent FR/NFR identifiers and traceability.
- System architecture and deployment/trust-boundary diagrams.
- OOAD/UML analysis that matches the actual implementation.
- Stable MCP Interface Contract covering Tools, Resource, Prompt, schemas and error behavior.
- Maintained MCP Core composition and read-only Linux telemetry implementation.
- Core unit tests and in-process MCP SDK Client contract tests.
- ADRs for material technology and architecture decisions.
- PR review records and an integration status summary for the three workstreams.

### Workstream 1 acceptance evidence

- Every requirement has a unique identifier, an owner or implementation location, and a defined verification method.
- Project Charter, SRS, Architecture, OOAD, MCP contracts and traceability references do not contradict one another.
- The server exposes the agreed four Tools, one Resource and one Prompt with stable names, schemas and documented behavior.
- Core telemetry returns timestamped, correctly-unitized data and handles process churn, PID reuse, invalid input and inaccessible resources safely.
- The application remains read-only; client input cannot become an arbitrary command, executable, filesystem path or systemd unit.
- Core quality checks and contract tests pass on the supported Python versions.
- Changes from Workstreams 2 and 3 are integrated through reviewed PRs on `team-handoff`, with conflicts resolved and regression evidence recorded.
- No final project acceptance is declared until the separate live OAuth, TLS/LAN, deployment and performance gates owned by the relevant workstreams have evidence.

### Responsibility boundaries

- **Workstream 1 owns:** requirements, system architecture, MCP public contract, core telemetry, technical standards, PR review and cross-workstream integration.
- **Workstream 2 owns:** implementation of authentication/authorization, journald reader, Keycloak, Caddy, Docker Compose, systemd and their deployment runbooks.
- **Workstream 3 owns:** independent integration/security/deployment/performance verification, repeatable test evidence and acceptance reporting.
- Workstream 1 reviews and coordinates Workstreams 2 and 3; it does not replace their implementation ownership or produce acceptance evidence on their behalf.

## Workstream 2 — Security & Infrastructure

**Owner:** member 2.

The implementation landed in Workstream 2's PR #4 and is included in the `integration/finalize-ubuntu2404` candidate. Workstream 2 retains ownership of these components: the Technical Lead may review and integrate changes but must not claim the owner's host-level verification without recorded evidence.

### Implementation ownership and final verification

1. Maintain the validated production/security settings in `config.py`, including normalized equality between the MCP audience and resource URI (trailing slashes are removed before comparison), plus the bounded introspection-cache TTL.
2. Own `src/linux_mcp_agent/auth_claims.py`: keep active state, issuer, finite expiry, not-before, exact audience/resource and scopes fail-closed.
3. Own `src/linux_mcp_agent/auth.py` and verify the official MCP SDK token-verifier integration with the configured Keycloak realm.
4. Maintain verifier wiring in `server.py`; keep the backend bound to loopback and protect the auth/session lifecycle.
5. Own `src/linux_mcp_agent/log_reader.py` and `config/log-sources.example.json`. Preserve alias-only access, server-owned `journalctl` argv, `shell=False`, line/time/byte bounds, best-effort redaction and safe errors.
6. Maintain the `read_allowed_log` handler without changing its public name or argument contract. Enforce `mcp.read` globally and `mcp.logs.read` before invoking journalctl.
7. Maintain `deploy/compose/compose.yaml` and safe `.env.example` for PostgreSQL, Keycloak and Caddy. Keep secrets out of Git and preserve PostgreSQL 18 volume semantics.
8. Maintain `deploy/caddy/Caddyfile`: internal TLS, exact hosts/routes, loopback upstreams, required OIDC routes only and admin routes unavailable from LAN.
9. Maintain `deploy/systemd/linux-mcp-agent.service` and `server.env.example`: dedicated non-root identity, restrictive sandboxing, explicit journal permissions and production configuration.
10. Keep the runbooks under `deploy/*/README.md` operationally accurate; document CA trust, firewall rules, upgrades, rollback and data-volume migration.

### Member 2 acceptance evidence

- Correct active token with exact issuer, expiry, resource/audience and `mcp.read` is accepted.
- Inactive, malformed, expired, wrong-issuer, wrong-audience/resource and missing-scope tokens are rejected before tool execution.
- Valid log alias works; unknown alias, traversal/injection, excess lines, timeout and oversized output fail safely.
- Missing `mcp.logs.read` never executes journalctl.
- Compose validates and services become healthy on Ubuntu 24.04.
- MCP and Keycloak bind to loopback; PostgreSQL is not LAN-published; only intended HTTPS ingress is exposed.
- Keycloak admin routes are unavailable from a second LAN device.
- Caddy CA trust works on the test client; the CA private key is never exported.
- systemd runs as a dedicated non-root user; journal group access and residual privilege are explained.

## Workstream 3 — QA, Integration and Acceptance

**Owner:** member 3.

Keep the core unit tests, in-process MCP contract test and the real TCP/Streamable HTTP integration test in the integration candidate. Maintain the independent security suite and acceptance matrix, then add deployment and performance evidence on the acceptance host; do not remove tests merely to get a green build.

### Required implementation

1. Independently execute and extend `tests/integration/` using the official MCP Client over actual Streamable HTTP. The candidate includes a local TCP smoke test; member 3 must additionally verify the deployed Ubuntu endpoint and the second LAN client.
2. Add `tests/security/` for valid/invalid OAuth tokens, issuer/audience/resource/scopes, log scope, alias allowlist, command boundary, timeout, output limit and redaction.
3. Add deployment smoke tests for Compose health, Caddy host/path behavior, TLS trust, loopback-only ports and a second LAN device.
4. Run and independently validate `scripts/benchmark_mcp.py` on the designated Ubuntu host. Measure each exposed tool separately and report p50/p95/p99, successful/error sample counts, host CPU/RAM/OS, Python and SDK versions. Extend the runner only when the acceptance environment reveals a concrete gap.
5. Record results under `reports/acceptance/`. Target: p95 at or below 2 seconds per tool on Ubuntu 24.04, excluding external LLM inference.
6. Maintain CI and a concise test report linking evidence to FR/NFR acceptance criteria. Include failures and limitations, not only successful screenshots.

### Member 3 acceptance evidence

- Core plus new integration/security/performance tests are repeatable.
- A second LAN client completes an authenticated Streamable HTTP session over trusted HTTPS.
- Invalid tokens, missing scopes and disallowed proxy paths are rejected.
- Every tool has recorded benchmark results against the p95 target.
- The report contains environment details, commands, raw results and known limitations.

## Branch and pull-request workflow

1. Treat `team-handoff` as the shared integration base.
2. Create feature branches from the latest `team-handoff`, for example `feature/security-keycloak-auth`, `feature/security-journald-reader`, `feature/infra-compose-caddy-systemd`, `test/mcp-http-integration`, `test/security-acceptance` and `test/performance-benchmarks`.
3. Open PRs back into `team-handoff`, not directly into `main`.
4. Each PR must include scope, design choices, tests run, actual results, known limitations and security/operational impact.
5. Group leader reviews and integrates PRs; member 3 verifies behavior after integration.
6. Do not merge `team-handoff` into `main` until all three workstreams pass acceptance.

## Definition of done

A file existing in the repository is not proof that a workstream is complete. Each owner must be able to explain the implementation, run it, demonstrate positive and negative cases, provide test evidence and respond to review comments. A green unit-test suite alone does not prove Keycloak, TLS, LAN or systemd acceptance.
