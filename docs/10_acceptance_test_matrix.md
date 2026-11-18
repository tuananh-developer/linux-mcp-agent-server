# Workstream 3: Acceptance Test Matrix

| ID | Yêu cầu (FR/NFR) | Môi trường test | Câu lệnh / Phương thức | Kết quả mong đợi | File bằng chứng | Trạng thái |
|---|---|---|---|---|---|---|
| **SEC-01** | Xác thực token (claims/cache) | Automated tests | `uv run pytest tests/test_auth_claims.py tests/test_config.py` | Valid/invalid claims, audience/resource, expiry and cache TTL are covered by unit tests; this is not live Keycloak acceptance. | `auth_claims_pass.png` | Unit evidence only; live OAuth pending |
| **SEC-02** | Log alias and command boundary | Automated tests | `uv run pytest tests/test_log_reader.py tests/security/test_log_security.py` | Unknown/traversal aliases are rejected; journalctl arguments are server-built and `shell=False`; the security test's malicious executable path is server-side configuration, not client-controlled input. | `log_security_pass.png` | Unit evidence only; live host acceptance pending |
| **INT-01** | Kết nối Streamable HTTP (LAN) | Server LAN | Dùng MCP Client truy cập IP server | Kết nối thành công, TLS hợp lệ. | `lan_connection.log` | Pending live deployment evidence |
| **INT-02** | Gọi 4 Tools cơ bản | Server LAN | Gọi tools qua MCP Client | Trả về JSON chuẩn xác. | `tools_invocation.log` | Pending live deployment evidence |
| **DEP-01** | Dịch vụ chạy dưới quyền non-root | Ubuntu 24.04 acceptance host | `systemctl show linux-mcp-agent -p User,Group,SupplementaryGroups` and `systemctl status linux-mcp-agent` | Service active under dedicated non-root identity with reviewed supplementary groups and sandbox. | `systemd_status.txt` | Pending WS3 host verification |
| **DEP-02** | Chặn truy cập Keycloak admin | Second LAN client | `curl --cacert <trusted-root.crt> -i https://auth.home.arpa/admin/` | Admin endpoints unavailable from LAN; only the explicitly allowlisted OIDC endpoints respond. | `keycloak_admin_block.txt` | Pending WS3 LAN verification |
| **PERF-01** | Benchmark p95 ≤ 2s | Ubuntu 24.04 acceptance host | `MCP_BENCHMARK_ACCESS_TOKEN=... MCP_BENCHMARK_LOG_ALIAS=... uv run python scripts/benchmark_mcp.py --iterations 100` | All four tools measured; no failed samples; minimum sample count met; each p95 ≤ 2000 ms. | `benchmark-ubuntu2404.json` | Pending WS3 live benchmark |

> **Status rule:** the two SEC rows above describe automated/unit-test coverage only. They are not live OAuth, proxy, TLS or host-level acceptance. Every pending row must be backed by sanitized raw output and the tested commit SHA before it is marked PASS.
