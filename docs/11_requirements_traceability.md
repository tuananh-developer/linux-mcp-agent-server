
# FR/NFR Requirements Traceability

**Project:** Linux MCP Agent Server  
**Baseline:** `docs/01_software_requirements_specification.md`  
**Owner:** Workstream 1 — Technical Lead  
**Last reviewed:** 2026-11-18

## How to read this matrix

- **Implemented/tested** means the repository contains implementation and automated tests for the stated behavior. It does not imply the latest integrated branch has passed a fresh CI run.
- **Live verification pending** means evidence must still be collected on the Ubuntu 24.04 acceptance host or from a second LAN client.
- A screenshot, configuration file or source-code presence alone is not proof that a deployment gate passed.
- The SRS is the single source of truth for requirement IDs and normative wording. This matrix supplies the file-level traceability.

## Functional requirements

| ID | Implementation / owner | Automated verification | Live / acceptance evidence and status |
|---|---|---|---|
| FR-001 | `src/linux_mcp_agent/server.py`; WS1 | `tests/integration/test_streamable_http.py::test_official_client_uses_real_streamable_http_transport`; `tests/test_mcp_contract.py` | Local TCP Streamable HTTP is covered. Deployed HTTPS session from a second device remains pending (WS3). |
| FR-002 | `src/linux_mcp_agent/system.py`; WS1 | `tests/test_system.py::test_system_metrics_has_expected_non_negative_values` | Unit coverage exists; representative Ubuntu host capture remains part of acceptance. |
| FR-003 | `system.py` exact administrator disk allowlist; WS1 | `tests/test_system.py::test_disk_usage_rejects_unknown_mount_point`, `test_disk_usage_returns_only_allowlisted_paths` | Host-specific mount allowlist must be configured and exercised on Ubuntu 24.04. |
| FR-004 | `system.py` bounded process list; WS1 | `tests/test_system.py::test_list_processes_limits_and_omits_sensitive_fields` plus invalid-limit/name-filter cases | Verify real host process output and privacy fields during acceptance. |
| FR-005 | `system.py` PID plus creation-time identity check; WS1 | `tests/test_system.py::test_list_processes_rejects_reused_pid` | Automated PID-reuse case exists; no additional live gate is specified. |
| FR-006 | `src/linux_mcp_agent/log_reader.py` alias-only journal reader; WS2 | `tests/test_log_reader.py::test_read_allowed_log_rejects_unknown_alias`, line-bound tests | Confirm configured aliases map to actual services on the acceptance host (WS2/WS3). |
| FR-007 | `log_reader.py` fixed argv, `shell=False`, time/output bounds and redaction; WS2 | `test_read_allowed_log_uses_fixed_argv_and_redacts_secrets`, `test_bounded_process_reader_enforces_timeout`, `test_bounded_process_reader_caps_output` in `tests/test_log_reader.py` | Confirm behavior against the host's real `journalctl` and configured service permissions. |
| FR-008 | `server.py` Resource `linux://system/summary`; WS1 | `tests/test_mcp_contract.py::test_official_mcp_client_discovers_and_invokes_server_capabilities`; TCP test reads the Resource | Deployed Resource read is included in WS3's live MCP session evidence. |
| FR-009 | `server.py` Prompt `health_check`; WS1 | `tests/test_mcp_contract.py::test_official_mcp_client_discovers_and_invokes_server_capabilities`; TCP test retrieves the Prompt | Deployed Prompt retrieval is included in WS3's live MCP session evidence. |
| FR-010 | `server.py` separate `/healthz` route; WS1 | ASGI lifecycle is covered by `tests/test_mcp_contract.py::test_mounted_asgi_app_starts_and_stops_mcp_session_manager`; response behavior is not fully covered by that test | Run `curl -fsS http://127.0.0.1:3002/healthz` on the deployed host and record output (WS3). |
| FR-011 | `auth.py`, `auth_claims.py`, `config.py` and log-scope guard in `server.py`; WS2 | `tests/test_auth_claims.py`, `tests/test_config.py`, `tests/test_mcp_contract.py::test_read_allowed_log_enforces_logs_scope_before_executing_journalctl` | Real Keycloak positive/negative token flows and the deployed realm's issuer, audience and scopes remain pending (WS2/WS3). |
| FR-012 | MCP handlers, `system.py`, `log_reader.py`, `auth_claims.py`; WS1/WS2 | Process privacy assertions, journal output bounds/redaction, invalid-token and log-scope tests in `tests/test_system.py`, `tests/test_log_reader.py`, `tests/test_auth_claims.py` and `tests/test_mcp_contract.py` | Review sanitized deployed responses and confirm no token, secret or raw private process metadata is exposed. |

## Non-functional requirements

| ID | Implementation / owner | Automated verification | Live / acceptance evidence and status |
|---|---|---|---|
| NFR-SEC-001 | Read-only tool surface; no arbitrary shell or mutation operations; WS1/WS2 | MCP contract, fixed-argv/`shell=False` tests and security regression tests | Final source review remains required after integration; no destructive host operations are part of acceptance. |
| NFR-SEC-002 | Loopback-only MCP/Keycloak listeners and Caddy as intended ingress; WS2 | `tests/test_config.py` loopback validation; Compose model validation in CI | Inspect `ss -lntp`, firewall and second-device routes on Ubuntu 24.04 (WS3). |
| NFR-SEC-003 | Keycloak introspection, claim validation, audience/resource binding and scopes; WS2 | `tests/test_auth_claims.py`, `tests/test_config.py`, log-scope MCP contract test | Real Keycloak positive/negative flows remain pending (WS2/WS3). |
| NFR-SEC-004 | Protected runtime environment files and secret placeholders; WS2 | Repository review of tracked examples/templates; secret values must not be committed | Verify actual secret file owner/mode and systemd environment permissions; never attach secret values (WS2/WS3). |
| NFR-SEC-005 | Journal data treated as untrusted, bounded and best-effort redacted; WS2 | Redaction, timeout, output cap and malformed timestamp tests in `tests/test_log_reader.py` | Validate real journald permissions and sanitized output on the target host. |
| NFR-PRF-001 | `scripts/benchmark_mcp.py`; WS3 executes and reports | Runner calculates per-tool p50/p95/p99 and fails acceptance when sample/error/latency gates are not met | No p95 result is claimed until a complete four-tool run is recorded on Ubuntu 24.04 (WS3). |
| NFR-PRF-002 | Bounded process sampling and journal execution; WS1/WS2 | `tests/test_system.py::test_process_sample_window_reports_actual_elapsed_time`, journal timeout/output-bound tests | Confirm measured bounds under the acceptance host's load. |
| NFR-REL-001 | `.github/workflows/ci.yml`; WS1 | Ruff, strict Pyright and pytest on Python 3.14/3.15 plus Compose model validation | CI run #44261484804 passed on commit `53fd681faab62938f42fe26261dea92b857f2698`: 97 tests passed on each Python version and Compose validation passed. A new run is required for any subsequent candidate commit. |
| NFR-DEP-001 | Ubuntu deployment guide and native systemd unit; WS2 | Configuration/Compose checks only; automated CI does not prove the host is deployed | Verify Ubuntu 24.04, dedicated non-root user, systemd sandbox and listeners on the target host. |
| NFR-MNT-001 | Environment-driven `Settings.from_env()`, production auth guard and runbooks; WS1/WS2 | `tests/test_config.py` for parsing, bounds, normalized resource/audience and production auth requirements | Review actual production environment file permissions and safe change/rollback procedure. |

## Ownership and closure

- **WS1 (Technical Lead):** maintain this matrix, canonical IDs, architecture/interface consistency, core tests, review and integration candidate.
- **WS2 (Security & Infrastructure):** maintain OAuth, journald, Keycloak, Caddy, Compose and systemd implementation; provide operational prerequisites and support live deployment.
- **WS3 (QA/Acceptance):** execute live HTTP/OAuth/TLS/LAN/deployment/performance checks and attach sanitized, reproducible evidence.

A requirement may be marked accepted only when both its applicable automated checks and its required live evidence are present. The current repository state is an integration candidate, not final project acceptance.
