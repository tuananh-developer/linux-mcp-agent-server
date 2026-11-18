from __future__ import annotations

from typing import Any

import httpx2
import pytest

from linux_mcp_agent.agent import AgentError, AgentSettings, OllamaGateway, clean_messages
from linux_mcp_agent.config import ConfigurationError, Settings
from linux_mcp_agent.server import build_asgi_app


@pytest.mark.parametrize("url", ["https://remote.example", "http://10.0.0.1:11434", "http://localhost:11434/path", "http://user:pass@localhost:11434"])
def test_ollama_only_accepts_loopback_origin(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("AGENT_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", url)
    with pytest.raises(ConfigurationError):
        AgentSettings.from_env()


@pytest.mark.parametrize("role", ["system", [], {}, None])
def test_client_rejects_invalid_conversation_role(role: object) -> None:
    with pytest.raises(AgentError, match="Invalid conversation role"):
        clean_messages([{"role": role, "content": "test"}])


@pytest.mark.asyncio
async def test_model_gateway_uses_server_tool_schemas_and_filters_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_PROVIDER", "ollama")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("MCP_PORT", "3002")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "127.0.0.1:3002")
    monkeypatch.setenv("AGENT_ENABLED", "true")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "4096")
    captured: list[dict[str, Any]] = []

    def fake_request(_self: OllamaGateway, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/api/tags":
            return {"models": [{"name": "qwen3:4b"}]}
        assert payload is not None
        captured.append(payload)
        return {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_system_metrics", "arguments": {}}}]}}

    monkeypatch.setattr(OllamaGateway, "_request", fake_request)
    app = build_asgi_app(Settings.from_env())
    async with app.router.lifespan_context(app), httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:3002"
    ) as client:
        headers = {"Origin": "http://127.0.0.1:3002"}
        assert (await client.get("/agent/status", headers=headers)).json()["available"] is True
        body = {"messages": [{"role": "user", "content": "Check Linux"}]}
        response = await client.post("/agent/chat", headers=headers, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["message"]["tool_calls"][0]["function"]["name"] == "get_system_metrics"
        assert {t["function"]["name"] for t in captured[0]["tools"]} == {"get_system_metrics", "get_disk_usage", "list_processes"}
        assert captured[0]["messages"][0]["role"] == "system"
        assert captured[0]["stream"] is False
        assert captured[0]["options"]["num_ctx"] == 4096
        assert (await client.post("/agent/chat", headers=headers, json={"messages": [{"role": "system", "content": "test"}]})).status_code == 400
        assert (await client.post("/agent/chat", headers={"Origin": "https://evil.invalid"}, json=body)).status_code == 403
        assert (await client.post("/agent/chat", headers={**headers, "Content-Type": "application/json"}, content=b"x" * 131073)).status_code == 413


@pytest.mark.asyncio
async def test_agent_gateway_requires_bearer_in_keycloak_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "keycloak")
    monkeypatch.setenv("MCP_INTROSPECTION_CLIENT_ID", "test-client")
    monkeypatch.setenv("MCP_INTROSPECTION_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("MCP_PORT", "3002")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "127.0.0.1:3002")
    app = build_asgi_app(Settings.from_env())
    async with app.router.lifespan_context(app), httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:3002"
    ) as client:
        assert (await client.get("/agent/status")).status_code == 401
        assert (await client.post("/agent/chat", json={"messages": []})).status_code == 401


@pytest.mark.parametrize("context", ["abc", "1024", "32769", "0"])
def test_agent_rejects_invalid_context(monkeypatch: pytest.MonkeyPatch, context: str) -> None:
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", context)
    with pytest.raises(ConfigurationError, match="OLLAMA_CONTEXT_LENGTH"):
        AgentSettings.from_env()


def test_agent_default_and_custom_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    assert AgentSettings.from_env().context_length == 4096
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "8192")
    assert AgentSettings.from_env().context_length == 8192
