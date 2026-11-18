import os

import httpx
import pytest

# TODO: Sẽ điền thông tin thật vào đây khi WS2 bàn giao
LIVE_HOST: str = os.getenv("MCP_LIVE_HOST", "https://<IP_CHUA_CO>")
VALID_TOKEN: str = os.getenv("MCP_VALID_TOKEN", "<TOKEN_CHUA_CO>")

INVALID_TOKENS: dict[str, str] = {
    "expired": "<EXPIRED_TOKEN>",
    "wrong_issuer": "<WRONG_ISSUER_TOKEN>",
    "wrong_audience": "<WRONG_AUDIENCE_TOKEN>",
    "missing_mcp_read": "<TOKEN_NO_READ_SCOPE>",
    "malformed": "Bearer abcdef12345",
    "inactive": "<INACTIVE_TOKEN>"
}

@pytest.fixture
def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {VALID_TOKEN}", "Content-Type": "application/json"}

@pytest.mark.asyncio
async def test_health_check_and_summary(headers: dict[str, str]) -> None:
    """INT-02: Kiểm tra health_check và linux://system/summary"""
    async with httpx.AsyncClient(verify=False) as client:
        # Giả định endpoint health và summary
        health_res = await client.get(f"{LIVE_HOST}/health")
        assert health_res.status_code == 200
        
        summary_res = await client.post(
            f"{LIVE_HOST}/mcp", 
            headers=headers, 
            json={"method": "linux://system/summary"}
        )
        assert summary_res.status_code == 200
        assert "os" in summary_res.json()

@pytest.mark.asyncio
async def test_mcp_tools_invocation(headers: dict[str, str]) -> None:
    """INT-01 & INT-02: Test gọi 4 tools cơ bản qua Streamable HTTP"""
    tools = ["read_log", "get_status", "list_services", "system_metrics"]
    async with httpx.AsyncClient(verify=False) as client:
        for tool in tools:
            res = await client.post(
                f"{LIVE_HOST}/mcp", 
                headers=headers, 
                json={"method": f"tools/{tool}", "params": {}}
            )
            assert res.status_code == 200, f"Tool {tool} failed"
            # Ghi log kết quả (đã sanitized)
            print(f"[{tool}] Success: {res.json()}")

@pytest.mark.parametrize("scenario,token", INVALID_TOKENS.items())
@pytest.mark.asyncio
async def test_oauth_negative_cases(scenario: str, token: str) -> None:
    """SEC-03: Kiểm tra các trường hợp Token lỗi bị từ chối"""
    bad_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(f"{LIVE_HOST}/mcp", headers=bad_headers, json={"method": "tools/read_log"})
        assert res.status_code in [401, 403], f"Bảo mật thất bại ở case: {scenario}"

@pytest.mark.asyncio
async def test_missing_logs_scope_denied() -> None:
    """SEC-04: Token có mcp.read nhưng thiếu mcp.logs.read bị chặn trước khi gọi journalctl"""
    token_no_log = os.getenv("MCP_TOKEN_NO_LOGS", "<TOKEN_CHUA_CO>")
    headers = {"Authorization": f"Bearer {token_no_log}"}
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(f"{LIVE_HOST}/mcp", headers=headers, json={"method": "tools/read_log"})
        assert res.status_code == 403
        assert "journalctl" not in res.text # Phải bị chặn trước khi chạm tới journalctl