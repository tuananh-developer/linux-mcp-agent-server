from __future__ import annotations

import json
from email.message import Message
from typing import Any
from urllib.error import HTTPError

import httpx2
import pytest

from linux_mcp_agent.agent import AgentError, AgentSettings, clean_messages
from linux_mcp_agent.config import Settings
from linux_mcp_agent.openai_gateway import OpenAIGateway, response_input
from linux_mcp_agent.server import build_asgi_app


def test_responses_history_keeps_call_ids() -> None:
    raw: list[dict[str, Any]] = [
        {"role": "user", "content": "Check host"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_abc", "function": {"name": "get_system_metrics", "arguments": {}}}]},
        {"role": "tool", "tool_name": "get_system_metrics", "tool_call_id": "call_abc", "content": '{"cpuUsagePercent":12}'},
    ]
    messages = clean_messages(raw)
    wire = response_input(messages)
    assert wire[1]["call_id"] == wire[2]["call_id"] == "call_abc"
    assert wire[2]["type"] == "function_call_output"
    with pytest.raises(AgentError, match="does not match"):
        response_input([{"role": "tool", "tool_name": "unknown", "content": "test"}])


@pytest.mark.asyncio
async def test_openai_gateway_payload_and_tool_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6-luna")
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "1024")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("MCP_PORT", "3002")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "127.0.0.1:3002")
    captured: list[dict[str, Any]] = []

    def fake_request(_self: OpenAIGateway, payload: dict[str, Any]) -> dict[str, Any]:
        captured.append(payload)
        if len(captured) > 1:
            return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Observed CPU: 12%"}]}]}
        return {"status": "completed", "output": [{"type": "function_call", "call_id": "call_metrics", "name": "get_system_metrics", "arguments": "{}"}], "usage": {"input_tokens": 100, "output_tokens": 20}}

    monkeypatch.setattr(OpenAIGateway, "_request", fake_request)
    app = build_asgi_app(Settings.from_env())
    async with app.router.lifespan_context(app), httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:3002") as client:
        status = (await client.get("/agent/status")).json()
        assert status["available"] is True and status["verified"] is False
        assert captured == []  # Opening the UI must not trigger paid inference.
        result = await client.post("/agent/chat", json={"messages": [{"role": "user", "content": "Check Linux"}]})
        assert result.status_code == 200, result.text
        assert result.json()["message"]["tool_calls"][0]["id"] == "call_metrics"
        assert "fake-test-key" not in result.text
        followup = await client.post("/agent/chat", json={"messages": [
            {"role": "user", "content": "Check Linux"}, result.json()["message"],
            {"role": "tool", "tool_name": "get_system_metrics", "tool_call_id": "call_metrics", "content": '{"cpuUsagePercent":12}'},
        ]})
        assert followup.status_code == 200, followup.text
        assert followup.json()["message"]["content"] == "Observed CPU: 12%"
        assert captured[1]["input"][-1]["call_id"] == "call_metrics"
    payload = captured[0]
    assert payload["model"] == "gpt-6-luna"
    assert payload["max_output_tokens"] == 1024
    assert payload["store"] is False
    assert payload["reasoning"] == {"effort": "none"}
    assert payload["parallel_tool_calls"] is False
    assert all(t["name"] != "read_allowed_log" for t in payload["tools"])
    assert "fake-test-key" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_missing_key_does_not_make_a_paid_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    gateway = OpenAIGateway(AgentSettings.from_env())
    assert (await gateway.status())["available"] is False
    with pytest.raises(AgentError, match="OPENAI_API_KEY"):
        await gateway.chat([{"role": "user", "content": "Hello"}], [])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output", "error"),
    [
        (None, "Invalid OpenAI output"),
        ([{"type": "message", "content": None}], "Invalid OpenAI message content"),
    ],
)
async def test_invalid_openai_response_returns_controlled_error(
    monkeypatch: pytest.MonkeyPatch, output: object, error: str
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    gateway = OpenAIGateway(AgentSettings.from_env())

    def fake_request(_payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "completed", "output": output}

    monkeypatch.setattr(gateway, "_request", fake_request)
    with pytest.raises(AgentError, match=error):
        await gateway.chat([{"role": "user", "content": "Hello"}], [])


def test_api_key_not_in_settings_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "private-test-key")
    assert "private-test-key" not in repr(AgentSettings.from_env())


@pytest.mark.parametrize("status", [401, 429])
def test_upstream_errors_never_echo_provider_body(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "private-test-key")
    gateway = OpenAIGateway(AgentSettings.from_env())

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise HTTPError("https://api.openai.com/v1/responses", status, "private-test-key", Message(), None)

    monkeypatch.setattr(gateway.opener, "open", fail)
    with pytest.raises(AgentError) as error:
        gateway._request({})  # pyright: ignore[reportPrivateUsage]
    assert "private-test-key" not in str(error.value)
