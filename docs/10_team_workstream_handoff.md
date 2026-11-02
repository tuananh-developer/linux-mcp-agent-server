# Team workstream handoff

**Shared integration base:** `team-handoff` · **Team size:** 3

This branch preserves the architecture/MCP core work while returning Security & Infrastructure implementation and QA/acceptance execution to the assigned owners. `main` remains unchanged as the full reference snapshot.

## Workstream 1 — Architecture, OOAD and MCP core

**Owner:** group leader.

Retained deliverables:
- SRS, project charter/scope, architecture, OOAD/UML and MCP interface contract.
- MCP composition in `src/linux_mcp_agent/server.py`.
- Linux CPU, memory, disk and process collectors in `src/linux_mcp_agent/system.py`.
- Minimal loopback runtime settings in `src/linux_mcp_agent/config.py`.
- MCP Resource, Prompt, three implemented telemetry tools and the registered journald tool contract.
- Core unit tests and in-process MCP SDK Client contract test.

Remaining responsibility: review incoming PRs, resolve interface conflicts, integrate the other workstreams and coordinate final acceptance. Do not count pending authentication, journald or deployment work as completed.

## Workstream 2 — Security & Infrastructure

**Owner:** member 2.

The implementation has deliberately been removed from this branch so the owner can design, implement, test and explain it. Use the architecture/security documents as requirements, not proof of a working stack.

### Required implementation

1. Extend `config.py` with validated production/security settings.
2. Implement `src/linux_mcp_agent/auth_claims.py`: fail-closed checks for active state, issuer, mandatory expiry, not-before, exact audience/resource and scopes.
3. Implement `src/linux_mcp_agent/auth.py` with the official MCP SDK token-verifier interface and Keycloak introspection.
4. Wire the verifier and SDK auth settings into `server.py`; keep the backend bound to loopback.
5. Implement `src/linux_mcp_agent/log_reader.py` and `config/log-sources.example.json`. Accept an alias only; resolve it to a server-owned systemd unit. Use fixed `journalctl` argv with `shell=False`; bound lines, execution time and output bytes; redact common secrets; return safe errors.
6. Complete the existing `read_allowed_log` MCP handler without changing its public name or argument contract. Enforce `mcp.read` globally and `mcp.logs.read` for journal access.
7. Implement `deploy/compose/compose.yaml` and safe `.env.example` for PostgreSQL, Keycloak and Caddy. No real secrets in Git.
8. Implement `deploy/caddy/Caddyfile`: internal TLS, exact hosts/routes, loopback upstreams, required OIDC routes only, admin routes unavailable from LAN.
9. Implement `deploy/systemd/linux-mcp-agent.service` and `server.env.example`: dedicated non-root user, restrictive sandboxing, explicit journal permissions and production config.
10. Complete the runbooks under `deploy/*/README.md`; document CA trust and firewall rules.

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

Keep existing core unit tests and the in-process MCP Client contract test as a baseline. Add independent suites and produce repeatable evidence; do not remove tests merely to get a green build.

### Required implementation

1. Add `tests/integration/` using the official MCP Client over actual Streamable HTTP. Verify initialization, capability discovery, tool calls, Resource reads and Prompt retrieval. Distinguish in-process tests from HTTP tests.
2. Add `tests/security/` for valid/invalid OAuth tokens, issuer/audience/resource/scopes, log scope, alias allowlist, command boundary, timeout, output limit and redaction.
3. Add deployment smoke tests for Compose health, Caddy host/path behavior, TLS trust, loopback-only ports and a second LAN device.
4. Add repeatable benchmarks under `tests/performance/` or `scripts/benchmark/`. Measure each tool separately and report p50/p95/p99, sample count, host CPU/RAM/OS, Python and SDK versions.
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
