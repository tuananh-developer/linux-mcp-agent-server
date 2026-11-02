from __future__ import annotations

import json

import pytest
from mcp import Client

from linux_mcp_agent.config import Settings
from linux_mcp_agent.server import build_asgi_app, build_mcp_server


@pytest.mark.asyncio
async def test_server_registers_the_required_mcp_interface(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "disabled")
    settings = Settings.from_env()
    server = build_mcp_server(settings)

    tools = await server.list_tools()
    resources = await server.list_resources()
    prompts = await server.list_prompts()

    assert {tool.name for tool in tools} == {
        "get_system_metrics",
        "get_disk_usage",
        "list_processes",
        "read_allowed_log",
    }
    assert [str(resource.uri) for resource in resources] == ["linux://system/summary"]
    assert [prompt.name for prompt in prompts] == ["health_check"]


@pytest.mark.asyncio
async def test_official_mcp_client_discovers_and_invokes_server_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "disabled")
    server = build_mcp_server(Settings.from_env())

    # Client(server) uses the SDK's in-process MCP transport. The deployed
    # Streamable HTTP endpoint is verified separately on the acceptance host.
    async with Client(server) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        prompts = await client.list_prompts()

        assert {tool.name for tool in tools.tools} == {
            "get_system_metrics",
            "get_disk_usage",
            "list_processes",
            "read_allowed_log",
        }
        assert [str(resource.uri) for resource in resources.resources] == [
            "linux://system/summary"
        ]
        assert [prompt.name for prompt in prompts.prompts] == ["health_check"]

        metrics = await client.call_tool("get_system_metrics")
        assert metrics.is_error is not True
        assert metrics.content

        summary = await client.read_resource("linux://system/summary")
        assert len(summary.contents) == 1
        summary_text = getattr(summary.contents[0], "text", None)
        assert isinstance(summary_text, str)
        summary_payload = json.loads(summary_text)
        assert "operatingSystem" in summary_payload
        assert "cpuUsagePercent" in summary_payload

        prompt = await client.get_prompt("health_check", {"focus": "overview"})
        assert len(prompt.messages) == 1
        prompt_text = getattr(prompt.messages[0].content, "text", None)
        assert isinstance(prompt_text, str)
        assert "read-only" in prompt_text


@pytest.mark.asyncio
async def test_mounted_asgi_app_starts_and_stops_mcp_session_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "disabled")
    settings = Settings.from_env()
    app = build_asgi_app(settings)

    async with app.router.lifespan_context(app):
        assert len(app.routes) == 2
