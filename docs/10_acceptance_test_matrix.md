# Workstream 3: Acceptance Test Matrix

| ID | Yêu cầu (FR/NFR) | Môi trường test | Câu lệnh / Phương thức | Kết quả mong đợi | File bằng chứng | Trạng thái |
|---|---|---|---|---|---|---|
| **SEC-01** | Xác thực Token (Valid/Expired/Scope) | Local CI | `uv run pytest tests/test_auth_claims.py` | Pass toàn bộ test. Token sai bị từ chối. | `auth_claims_pass.png` | ✅ PASS |
| **SEC-02** | Ngăn Path Traversal & Injection | Local CI | `uv run pytest tests/security/test_log_security.py` | Báo lỗi khi truy cập ngoài cấu hình. *(Proven by existing tests with fixed-argv and shell=False in tests/test_log_reader.py)* | `log_security_pass.png` | ✅ PASS |
| **INT-01** | Kết nối Streamable HTTP (LAN) | Server LAN | Dùng MCP Client truy cập IP server | Kết nối thành công, TLS hợp lệ. | `lan_connection.log` | Chờ WS2 |
| **INT-02** | Gọi 4 Tools cơ bản | Server LAN | Gọi tools qua MCP Client | Trả về JSON chuẩn xác. | `tools_invocation.log` | Chờ WS2 |
| **DEP-01** | Dịch vụ chạy dưới quyền non-root | Server SSH | `systemctl status linux-mcp-agent` & `ps aux` | Service active, chạy bằng user riêng biệt. | `systemd_status.png` | Chờ WS2 |
| **DEP-02** | Chặn truy cập Keycloak admin | Server LAN | `curl -k https://<IP>/auth/admin` | Bị từ chối (403/404). | `keycloak_block.png` | Chờ WS2 |
| **PERF-01**| Benchmark p95 ≤ 2s | Server SSH | `uv run python scripts/benchmark_mcp.py` | p95 của 4 tools < 2000ms. | `benchmark.json` | Chờ WS2 |