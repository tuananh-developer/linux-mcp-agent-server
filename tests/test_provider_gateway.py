from __future__ import annotations

from email.message import Message
from io import BytesIO
from typing import Any
from urllib.error import HTTPError

import httpx2
import pytest
from pathlib import Path
from mcp.server.auth.provider import AccessToken

from linux_mcp_agent.agent import AgentError, clean_messages
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


@pytest.mark.parametrize("api_key", ["token-ấ-invalid", "token-with internal-space"])
def test_provider_settings_reject_non_ascii_or_whitespace_api_keys(api_key: str) -> None:
    with pytest.raises(AgentError, match="ASCII"):
        ProviderSettings.from_payload({
            "provider": "openrouter",
            "model": "openrouter/free",
            "api_key": api_key,
        })

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
        ("openrouter", "/models", {"data": [{"id": "nvidia/nemotron-3-ultra-550b-a55b:free"}]}, "nvidia/nemotron-3-ultra-550b-a55b:free"),
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
    assert result["models"] == ([expected, "openrouter/free"] if provider == "openrouter" else [expected])
    assert seen == [("GET", path)]
    assert "dummy-provider-key" not in str(result)


@pytest.mark.parametrize("selected_model", ["openrouter/free", "some/model-249"])
@pytest.mark.asyncio
async def test_openrouter_selected_model_and_free_router_survive_large_catalog(
    monkeypatch: pytest.MonkeyPatch,
    selected_model: str,
) -> None:
    settings = ProviderSettings.from_payload({
        "provider": "openrouter",
        "model": selected_model,
        "api_key": "dummy-openrouter-key",
    })
    gateway = ProviderGateway(settings)
    listing = {"data": [{"id": f"some/model-{index}"} for index in range(250)]}

    def fake_request(_method: str, _path: str, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return listing

    monkeypatch.setattr(gateway, "_request", fake_request)
    result = await gateway.test_connection()

    assert result["available"] is True
    assert selected_model in result["models"]
    assert "openrouter/free" in result["models"]
    assert len(result["models"]) == 200


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
async def test_openrouter_free_router_is_available_even_when_not_in_model_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = ProviderSettings.from_payload({
        "provider": "openrouter",
        "model": "openrouter/free",
        "api_key": "dummy-openrouter-key",
    })
    gateway = ProviderGateway(settings)

    def fake_request(_method: str, _path: str, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"data": [{"id": "some/paid-model"}]}

    monkeypatch.setattr(gateway, "_request", fake_request)
    result = await gateway.test_connection()
    assert result["available"] is True
    assert "openrouter/free" in result["models"]


def test_openrouter_uses_openai_compatible_endpoint_and_headers() -> None:
    settings = ProviderSettings.from_payload({
        "provider": "openrouter",
        "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "api_key": "openrouter-test-key",
    })
    gateway = ProviderGateway(settings)
    assert gateway.base_url == "https://openrouter.ai/api/v1"
    headers = gateway._headers()  # pyright: ignore[reportPrivateUsage]
    assert headers["Authorization"] == "Bearer openrouter-test-key"
    assert headers["HTTP-Referer"] == "https://mcp.home.arpa"
    assert headers["X-Title"] == "Linux Observatory"


@pytest.mark.asyncio
async def test_openrouter_chat_sends_tools_with_compatible_provider_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = ProviderGateway(ProviderSettings.from_payload({
        "provider": "openrouter",
        "model": "openrouter/free",
        "api_key": "dummy-openrouter-key",
    }))
    captured: list[dict[str, Any]] = []
    tool_defs = [{
        "type": "function",
        "function": {
            "name": "get_system_metrics",
            "description": "Read CPU and memory metrics",
            "parameters": {
                "type": "object",
                "properties": {"include_details": {"type": "boolean"}},
                "additionalProperties": False,
            },
        },
    }]

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
    result = await gateway.chat([{"role": "user", "content": "Check CPU"}], tool_defs)
    assert result["message"]["tool_calls"][0]["id"] == "call_cpu"
    assert captured[0]["model"] == "openrouter/free"
    assert captured[0]["max_completion_tokens"] == 1536
    assert "max_tokens" not in captured[0]
    assert captured[0]["provider"] == {"require_parameters": True}
    assert captured[0]["tools"] == tool_defs
    assert "parallel_tool_calls" not in captured[0]
    assert "tool_choice" not in captured[0]
    assert result["usage"] == {"input_tokens": 12, "output_tokens": 3}


def test_http_400_includes_provider_reason_without_exposing_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = ProviderSettings.from_payload({
        "provider": "openrouter",
        "model": "openrouter/free",
        "api_key": "secret-test-key",
    })
    gateway = ProviderGateway(settings)

    def reject_request(_request: Any, timeout: int) -> Any:
        raise HTTPError(
            "https://openrouter.ai/api/v1/chat/completions",
            400,
            "Bad Request",
            Message(),
            BytesIO(b'{"error":{"message":"Invalid tool schema; secret-test-key"}}'),
        )

    monkeypatch.setattr(gateway.opener, "open", reject_request)
    with pytest.raises(AgentError, match="Invalid tool schema") as exc_info:
        gateway._request("POST", "/chat/completions", {"model": "openrouter/free"})  # pyright: ignore[reportPrivateUsage]
    assert "secret-test-key" not in str(exc_info.value)
    assert "[đã ẩn]" in str(exc_info.value)


@pytest.mark.asyncio
async def test_openrouter_preserves_reasoning_details_across_tool_and_user_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = ProviderGateway(ProviderSettings.from_payload({
        "provider": "openrouter",
        "model": "openrouter/free",
        "api_key": "dummy-openrouter-key",
    }))
    tool_round_details = [{
        "type": "reasoning.text",
        "text": "opaque tool-round reasoning",
        "signature": "opaque-tool-signature",
    }]
    final_turn_details = [{
        "type": "reasoning.text",
        "text": "opaque final-turn reasoning",
        "signature": "opaque-final-signature",
    }]
    responses = [
        {
            "choices": [{"message": {
                "role": "assistant",
                "content": "",
                "reasoning_details": tool_round_details,
                "tool_calls": [{"id": "call_cpu", "function": {
                    "name": "get_system_metrics", "arguments": "{}",
                }}],
            }}],
        },
        {
            "choices": [{"message": {
                "role": "assistant",
                "content": "CPU usage is 12%.",
                "reasoning_details": final_turn_details,
            }}],
        },
        {
            "choices": [{"message": {
                "role": "assistant",
                "content": "RAM is also within normal range.",
            }}],
        },
    ]
    captured: list[dict[str, Any]] = []

    def fake_request(_method: str, _path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        assert payload is not None
        captured.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(gateway, "_request", fake_request)
    first = await gateway.chat([{"role": "user", "content": "Check CPU"}], [])
    next_messages = clean_messages([
        {"role": "user", "content": "Check CPU"},
        first["message"],
        {
            "role": "tool",
            "tool_name": "get_system_metrics",
            "tool_call_id": first["message"]["tool_calls"][0]["id"],
            "content": '{"cpuUsagePercent":12}',
        },
    ])
    second = await gateway.chat(next_messages, [])
    assert second["message"]["content"] == "CPU usage is 12%."
    assert second["message"]["provider_metadata"]["openrouter_reasoning_details"] == final_turn_details

    continued_messages = clean_messages([
        *next_messages,
        second["message"],
        {"role": "user", "content": "How is RAM?"},
    ])
    third = await gateway.chat(continued_messages, [])
    assert third["message"]["content"] == "RAM is also within normal range."
    replayed_tool_assistant = captured[1]["messages"][2]
    replayed_final_assistant = captured[2]["messages"][4]
    assert replayed_tool_assistant["reasoning_details"] == tool_round_details
    assert replayed_final_assistant["reasoning_details"] == final_turn_details

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


@pytest.mark.asyncio
async def test_encrypted_provider_credentials_are_scoped_to_keycloak_subject(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "keycloak")
    monkeypatch.setenv("MCP_INTROSPECTION_CLIENT_ID", "test-client")
    monkeypatch.setenv("MCP_INTROSPECTION_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("MCP_PORT", "3002")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "127.0.0.1:3002")
    monkeypatch.setenv("PROVIDER_VAULT_KEY_FILE", str(tmp_path / "vault.key"))
    monkeypatch.setenv("PROVIDER_VAULT_FILE", str(tmp_path / "provider-credentials.json"))
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    (tmp_path / "vault.key").write_bytes(b"v" * 32)
    (tmp_path / "vault.key").chmod(0o600)

    async def verify(_self: object, token: str) -> AccessToken | None:
        if token not in {"user-a", "user-b"}:
            return None
        return AccessToken(
            token=token,
            client_id="browser",
            scopes=["mcp.read"],
            expires_at=9_999_999_999,
            resource="https://mcp.home.arpa/mcp",
            subject=token,
        )

    async def fake_test(self: ProviderGateway) -> dict[str, Any]:
        return {
            "provider": self.settings.provider,
            "model": self.settings.model,
            "available": True,
            "models": [self.settings.model],
            "message": "Ready",
        }

    async def fake_chat(
        self: ProviderGateway, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        assert self.settings.api_key == "user-a-secret"
        assert messages[0]["content"] == "Read CPU"
        return {
            "provider": self.settings.provider,
            "model": self.settings.model,
            "message": {"role": "assistant", "content": "OK", "tool_calls": []},
        }

    monkeypatch.setattr("linux_mcp_agent.auth.KeycloakIntrospectionVerifier.verify_token", verify)
    monkeypatch.setattr(ProviderGateway, "test_connection", fake_test)
    monkeypatch.setattr(ProviderGateway, "chat", fake_chat)
    app = build_asgi_app(Settings.from_env())

    async with app.router.lifespan_context(app), httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:3002"
    ) as client:
        base_headers = {
            "Origin": "http://127.0.0.1:3002",
            "Content-Type": "application/json",
        }
        user_a = {**base_headers, "Authorization": "Bearer user-a"}
        user_b = {**base_headers, "Authorization": "Bearer user-b"}
        provider_config = {
            "provider": "openrouter",
            "model": "openrouter/free",
            "api_key": "user-a-secret",
        }

        tested = await client.post(
            "/agent/test",
            headers=user_a,
            json={"provider_config": provider_config, "remember": True},
        )
        assert tested.status_code == 200, tested.text
        assert tested.json()["credential_saved"] is True
        assert "user-a-secret" not in tested.text

        listed_a = await client.get("/agent/credentials", headers=user_a)
        assert listed_a.status_code == 200, listed_a.text
        assert listed_a.json()["credentials"] == [{
            "provider": "openrouter",
            "model": "openrouter/free",
            "updated_at": listed_a.json()["credentials"][0]["updated_at"],
        }]
        assert "user-a-secret" not in listed_a.text

        listed_b = await client.get("/agent/credentials", headers=user_b)
        assert listed_b.status_code == 200
        assert listed_b.json()["credentials"] == []

        chatted = await client.post(
            "/agent/chat",
            headers=user_a,
            json={
                "provider_config": {"provider": "openrouter", "model": "openrouter/free"},
                "messages": [{"role": "user", "content": "Read CPU"}],
            },
        )
        assert chatted.status_code == 200, chatted.text
        assert chatted.json()["message"]["content"] == "OK"

        denied = await client.post(
            "/agent/chat",
            headers=user_b,
            json={
                "provider_config": {"provider": "openrouter", "model": "openrouter/free"},
                "messages": [{"role": "user", "content": "Read CPU"}],
            },
        )
        assert denied.status_code == 400
        assert "Chưa có API key đã lưu" in denied.json()["error"]

        deleted_by_b = await client.delete("/agent/credentials/openrouter", headers=user_b)
        assert deleted_by_b.status_code == 200
        assert deleted_by_b.json()["deleted"] is False
        assert (await client.get("/agent/credentials", headers=user_a)).json()["credentials"]

        deleted_by_a = await client.delete("/agent/credentials/openrouter", headers=user_a)
        assert deleted_by_a.status_code == 200
        assert deleted_by_a.json()["deleted"] is True
        assert (await client.get("/agent/credentials", headers=user_a)).json()["credentials"] == []
