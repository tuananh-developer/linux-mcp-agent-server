"""Exercise browser-origin HTTP requests through the actual ASGI MCP transport."""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest
from mcp.server.auth.provider import AccessToken

from linux_mcp_agent.config import Settings
from linux_mcp_agent.server import build_asgi_app


def rpc_result(response: httpx2.Response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    if "text/event-stream" in response.headers.get("content-type", ""):
        for line in response.text.splitlines():
            if line.startswith("data:"):
                message = json.loads(line[5:])
                if "result" in message:
                    return message["result"]
        raise AssertionError("No MCP result in event stream")
    return response.json()["result"]


@pytest.mark.asyncio
async def test_dashboard_browser_session_calls_real_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("MCP_PORT", "3002")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "127.0.0.1:3002")
    monkeypatch.setenv("ALLOWED_DISK_PATHS", "/")
    app = build_asgi_app(Settings.from_env())
    async with app.router.lifespan_context(app), httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:3002"
    ) as client:
        page = await client.get("/")
        assert page.status_code == 200
        assert "Linux Observatory" in page.text
        assert "Tổng quan hệ thống" in page.text
        assert 'id="cpu-value"' in page.text
        assert "Tự động cập nhật mỗi 5 giây" in page.text
        assert 'id="login-keycloak"' in page.text
        assert 'id="bearer-token"' not in page.text
        overview_script = await client.get("/dashboard/assets/overview.js")
        assert overview_script.status_code == 200
        assert "REFRESH_INTERVAL_MS=5000" in overview_script.text
        assert "HISTORY_LIMIT=60" in overview_script.text
        assistant = await client.get("/assistant")
        assert assistant.status_code == 200
        assert 'id="chat-form"' in assistant.text
        assert 'id="login-keycloak"' in assistant.text
        assert 'id="bearer-token"' not in assistant.text
        assert 'id="agent-remember-key"' in assistant.text
        assert 'id="agent-remember-key" type="checkbox"' in assistant.text
        assert "Lưu API key đã mã hóa trên MCP Server" in assistant.text
        agent_ui = await client.get("/dashboard/assets/agent-ui.js")
        assert agent_ui.status_code == 200
        assert "agent/credentials" in agent_ui.text
        assert "localStorage" not in agent_ui.text
        assert "credential_saved" in agent_ui.text
        for removed_screen in ("view-overview", "view-processes", "view-logs", "view-explorer"):
            assert f'id="{removed_screen}"' not in page.text
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        for asset in ("overview.css", "overview.js", "app.css", "app.js", "mcp-client.mjs", "keycloak-auth.mjs", "agent-ui.js", "agent-client.mjs", "markdown.mjs"):
            result = await client.get(f"/dashboard/assets/{asset}")
            assert result.status_code == 200
            assert result.headers["x-content-type-options"] == "nosniff"
            if asset == "markdown.mjs":
                assert "export function parseMarkdown" in result.text
                assert "text/javascript" in result.headers["content-type"]
        assert (await client.get("/dashboard/assets/../../config.py")).status_code == 404
        headers = {
            "Accept": "application/json, text/event-stream",
            "Origin": "http://127.0.0.1:3002",
        }
        response = await client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "dashboard-test", "version": "1"}},
        })
        result = rpc_result(response)
        headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]
        headers["MCP-Protocol-Version"] = result["protocolVersion"]
        initialized = await client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "method": "notifications/initialized",
        })
        assert initialized.status_code == 202
        tools = rpc_result(await client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        }))
        assert {tool["name"] for tool in tools["tools"]} == {"get_system_metrics", "get_disk_usage", "list_processes", "read_allowed_log", "get_network_stats", "get_service_status", "check_port", "get_system_alerts"}
        metrics = rpc_result(await client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "get_system_metrics", "arguments": {}},
        }))
        assert metrics.get("isError") is not True
        payload = metrics.get("structuredContent") or json.loads(metrics["content"][0]["text"])
        assert "cpuUsagePercent" in payload
        hostile = {**headers, "Origin": "https://attacker.invalid"}
        assert (await client.post("/mcp", headers=hostile, json={
            "jsonrpc": "2.0", "id": 4, "method": "tools/list",
        })).status_code == 403
        assert (await client.delete("/mcp", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_dashboard_shell_does_not_bypass_mcp_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "keycloak")
    monkeypatch.setenv("MCP_INTROSPECTION_CLIENT_ID", "test-client")
    monkeypatch.setenv("MCP_INTROSPECTION_CLIENT_SECRET", "not-a-real-secret")
    monkeypatch.setenv("MCP_PORT", "3002")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "127.0.0.1:3002")

    async def verify(_self: object, token: str) -> AccessToken | None:
        if token != "valid-test-token":
            return None
        return AccessToken(token=token, client_id="test", scopes=["mcp.read"],
                           resource="https://mcp.home.arpa/mcp", expires_at=9_999_999_999)

    monkeypatch.setattr("linux_mcp_agent.auth.KeycloakIntrospectionVerifier.verify_token", verify)
    app = build_asgi_app(Settings.from_env())
    async with app.router.lifespan_context(app), httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:3002"
    ) as client:
        page = await client.get("/")
        assert page.status_code == 200
        assert "not-a-real-secret" not in page.text
        headers = {"Accept": "application/json, text/event-stream", "Origin": "http://127.0.0.1:3002"}
        body: dict[str, Any] = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "dashboard-auth-test", "version": "1"}},
        }
        assert (await client.post("/mcp", headers=headers, json=body)).status_code == 401
        assert (await client.post("/mcp", headers={**headers, "Authorization": "Bearer invalid"}, json=body)).status_code == 401
        headers["Authorization"] = "Bearer valid-test-token"
        response = await client.post("/mcp", headers=headers, json=body)
        result = rpc_result(response)
        headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]
        headers["MCP-Protocol-Version"] = result["protocolVersion"]
        await client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        denied = rpc_result(await client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "read_allowed_log", "arguments": {"alias": "ssh", "lines": 5}},
        }))
        assert denied["isError"] is True
        assert "INSUFFICIENT_SCOPE" in denied["content"][0]["text"]
