from __future__ import annotations

from typing import Any

import httpx2
import pytest

from linux_mcp_agent.agent import AgentError
from linux_mcp_agent.config import Settings
from linux_mcp_agent.provider_gateway import ProviderGateway, ProviderSettings
from linux_mcp_agent.server import build_asgi_app


def test_provider_settings_require_key_and_hide_it_from_repr() -> None:
    with pytest.raises(AgentError, match="API key"):
        ProviderSettings.from_payload({"provider": "gemini", "model": "gemini-3.8-flash"})
    settings = ProviderSettings.from_payload({
        "provider": "openai", "model": "gpt-4.1-mini", "api_key": "secret-test-key",
    })
    assert "secret-test-key" not in repr(settings)

@pytest.mark.parametrize("provider", [None, [], {}, 123, "unsupported"])
def test_provider_settings_reject_invalid_provider_type(provider: object) -> None:
    with pytest.raises(AgentError, match="không được hỗ trợ"):
        ProviderSettings.from_payload({"provider": provider, "model": "test-model", "api_key": "key"})


def test_ollama_rejects_malformed_url_without_server_error() -> None:
    with pytest.raises(AgentError, match="base URL"):
        ProviderSettings.from_payload({
            "provider": "ollama", "model": "qwen3:4b", "base_url": "http://[",
        })


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://192.168.1.10:11434",
        "http://localhost:11434/path",
        "http://user:pass@127.0.0.1:11434",
    ],
)
def test_ollama_rejects_non_loopback_or_non_origin_urls(url: str) -> None:
    with pytest.raises(AgentError, match="loopback"):
        ProviderSettings.from_payload({
            "provider": "ollama", "model": "qwen3:4b", "base_url": url,
        })


@pytest.mark.parametrize(
    ("provider", "path", "listing", "expected"),
    [
        ("openai", "/models", {"data": [{"id": "gpt-4.1-mini"}]}, "gpt-4.1-mini"),
        ("anthropic", "/models", {"data": [{"id": "claude-sonnet-4-6"}]}, "claude-sonnet-4-6"),
        ("gemini", "/models", {"models": [
            {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/text-embedding", "supportedGenerationMethods": ["embedContent"]},
        ]}, "gemini-3.8-flash"),
        ("ollama", "/api/tags", {"models": [{"name": "qwen3:4b"}]}, "qwen3:4b"),
    ],
)
@pytest.mark.asyncio
async def test_connection_check_lists_models(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    path: str,
    listing: dict[str, Any],
    expected: str,
) -> None:
    settings = ProviderSettings.from_payload({
        "provider": provider,
        "model": expected,
        "api_key": "" if provider == "ollama" else "dummy-provider-key",
    })
    gateway = ProviderGateway(settings)
    seen: list[tuple[str, str]] = []

    def fake_request(method: str, request_path: str, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        seen.append((method, request_path))
        return listing

    monkeypatch.setattr(gateway, "_request", fake_request)
    result = await gateway.test_connection()
    assert result["available"] is True
    assert result["model"] == expected
    assert result["models"] == [expected]
    assert seen == [("GET", path)]
    assert "dummy-provider-key" not in str(result)


@pytest.mark.asyncio
async def test_openai_chat_normalizes_function_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = ProviderGateway(ProviderSettings.from_payload({
        "provider": "openai", "model": "gpt-4.1-mini", "api_key": "dummy-key",
    }))
    captured: list[dict[str, Any]] = []

    def fake_request(_method: str, _path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        assert payload is not None
        captured.append(payload)
        return {
            "choices": [{"message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call_cpu", "function": {
                    "name": "get_system_metrics", "arguments": "{}",
                }}],
            }}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }

    monkeypatch.setattr(gateway, "_request", fake_request)
    result = await gateway.chat([{"role": "user", "content": "Check CPU"}], [])
    assert result["message"]["tool_calls"][0]["id"] == "call_cpu"
    assert result["usage"] == {"input_tokens": 12, "output_tokens": 3}
    assert captured[0]["model"] == "gpt-4.1-mini"
    assert captured[0]["max_completion_tokens"] == 1536
    assert "max_tokens" not in captured[0]
    assert "dummy-key" not in str(result)


@pytest.mark.asyncio
async def test_gemini_chat_maps_function_call_and_history(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = ProviderGateway(ProviderSettings.from_payload({
        "provider": "gemini", "model": "gemini-3.8-flash", "api_key": "dummy-key",
    }))
    captured: list[dict[str, Any]] = []

    def fake_request(_method: str, _path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        assert payload is not None
        captured.append(payload)
        return {
            "candidates": [{"content": {"parts": [{
                "functionCall": {"name": "get_system_metrics", "args": {}},
                "thoughtSignature": "opaque-gemini-signature",
            }]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2},
        }

    monkeypatch.setattr(gateway, "_request", fake_request)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "Check CPU"},
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": "call_a", "function": {"name": "get_system_metrics", "arguments": {}},
        }]},
        {"role": "tool", "tool_name": "get_system_metrics", "tool_call_id": "call_a", "content": '{"cpuUsagePercent":12}'},
        {"role": "tool", "tool_name": "get_disk_usage", "tool_call_id": "call_b", "content": '{"filesystems":[]}'},
    ]
    result = await gateway.chat(messages, [])
    tool_call = result["message"]["tool_calls"][0]
    assert tool_call["function"]["name"] == "get_system_metrics"
    assert tool_call["provider_metadata"]["gemini_thought_signature"] == "opaque-gemini-signature"
    assert result["usage"]["input_tokens"] == 10
    history = captured[0]["contents"]
    function_responses = [
        part["functionResponse"]
        for item in history
        for part in item["parts"]
        if "functionResponse" in part
    ]
    assert len(function_responses) == 2
    assert history[-1]["role"] == "user"
    assert len(history[-1]["parts"]) == 2


@pytest.mark.asyncio
async def test_gemini_thought_signature_survives_the_next_tool_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = ProviderGateway(ProviderSettings.from_payload({
        "provider": "gemini", "model": "gemini-3.8-flash", "api_key": "dummy-key",
    }))
    captured: list[dict[str, Any]] = []
    responses = [
        {
            "candidates": [{"content": {"parts": [{
                "functionCall": {"name": "get_system_metrics", "args": {}},
                "thoughtSignature": "opaque-signature-must-not-change",
            }]}}],
        },
        {"candidates": [{"content": {"parts": [{"text": "CPU usage is 12%."}]}}]},
    ]

    def fake_request(_method: str, _path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        assert payload is not None
        captured.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(gateway, "_request", fake_request)
    first = await gateway.chat([{"role": "user", "content": "Check CPU"}], [])
    assistant_message = first["message"]
    tool_call = assistant_message["tool_calls"][0]
    next_messages = [
        {"role": "user", "content": "Check CPU"},
        assistant_message,
        {
            "role": "tool",
            "tool_name": "get_system_metrics",
            "tool_call_id": tool_call["id"],
            "content": '{"cpuUsagePercent":12}',
        },
    ]

    # Simulate the same validation applied to every subsequent browser request.
    from linux_mcp_agent.agent import clean_messages
    cleaned = clean_messages(next_messages)
    second = await gateway.chat(cleaned, [])
    assert second["message"]["content"] == "CPU usage is 12%."

    replayed_part = captured[1]["contents"][1]["parts"][0]
    assert replayed_part["functionCall"] == {
        "name": "get_system_metrics",
        "args": {},
    }
    assert replayed_part["thoughtSignature"] == "opaque-signature-must-not-change"


@pytest.mark.asyncio
async def test_anthropic_chat_normalizes_tool_use(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = ProviderGateway(ProviderSettings.from_payload({
        "provider": "anthropic", "model": "claude-sonnet-4-6", "api_key": "dummy-key",
    }))
    captured: list[dict[str, Any]] = []

    def fake_request(_method: str, _path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        assert payload is not None
        captured.append(payload)
        return {
            "content": [{"type": "tool_use", "id": "toolu_123", "name": "get_system_metrics", "input": {}}],
            "usage": {"input_tokens": 9, "output_tokens": 2},
        }

    monkeypatch.setattr(gateway, "_request", fake_request)
    result = await gateway.chat([{"role": "user", "content": "Check CPU"}], [{
        "type": "function", "function": {"name": "get_system_metrics", "description": "Read CPU", "parameters": {"type": "object", "properties": {}}},
    }])
    assert result["message"]["tool_calls"][0]["id"] == "toolu_123"
    assert captured[0]["tools"][0]["name"] == "get_system_metrics"
    assert captured[0]["tools"][0]["input_schema"] == {
        "type": "object", "properties": {},
    }
    assert "parameters" not in captured[0]["tools"][0]
    assert result["usage"]["output_tokens"] == 2


@pytest.mark.asyncio
async def test_ollama_chat_uses_loopback_and_native_tool_format(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = ProviderGateway(ProviderSettings.from_payload({
        "provider": "ollama", "model": "qwen3:4b", "base_url": "http://127.0.0.1:11434",
    }))
    captured: list[dict[str, Any]] = []

    def fake_request(_method: str, _path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        assert payload is not None
        captured.append(payload)
        return {"message": {"role": "assistant", "content": "CPU looks normal."}, "prompt_eval_count": 6, "eval_count": 4}

    monkeypatch.setattr(gateway, "_request", fake_request)
    result = await gateway.chat([{"role": "user", "content": "Check CPU"}], [])
    assert result["message"]["content"] == "CPU looks normal."
    assert captured[0]["stream"] is False


@pytest.mark.asyncio
async def test_per_request_provider_routes_work_when_legacy_agent_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("AGENT_ENABLED", "false")
    monkeypatch.setenv("MCP_PORT", "3002")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "127.0.0.1:3002")

    async def fake_test(self: ProviderGateway) -> dict[str, Any]:
        assert self.settings.api_key == "ephemeral-test-secret"
        return {"provider": "gemini", "model": "gemini-3.8-flash", "available": True, "models": ["gemini-3.8-flash"]}

    async def fake_chat(
        self: ProviderGateway, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        assert self.settings.api_key == "ephemeral-test-secret"
        assert messages[0]["content"] == "Check host"
        return {"provider": self.settings.provider, "model": self.settings.model, "message": {"role": "assistant", "content": "Ready", "tool_calls": []}}

    monkeypatch.setattr(ProviderGateway, "test_connection", fake_test)
    monkeypatch.setattr(ProviderGateway, "chat", fake_chat)
    app = build_asgi_app(Settings.from_env())
    async with app.router.lifespan_context(app), httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:3002"
    ) as client:
        headers = {"Origin": "http://127.0.0.1:3002"}
        provider_config = {
            "provider": "gemini", "model": "gemini-3.8-flash", "api_key": "ephemeral-test-secret",
        }
        tested = await client.post("/agent/test", headers=headers, json={"provider_config": provider_config})
        assert tested.status_code == 200, tested.text
        assert tested.json()["available"] is True
        assert "ephemeral-test-secret" not in tested.text

        chatted = await client.post("/agent/chat", headers=headers, json={
            "provider_config": provider_config,
            "messages": [{"role": "user", "content": "Check host"}],
        })
        assert chatted.status_code == 200, chatted.text
        assert chatted.json()["message"]["content"] == "Ready"
        assert "ephemeral-test-secret" not in chatted.text
