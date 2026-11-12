from __future__ import annotations

import json

import pytest
from mcp import Client

from linux_mcp_agent.config import Settings
from linux_mcp_agent.server import build_asgi_app, build_mcp_server


@pytest.mark.asyncio
async def test_server_registers_required_mcp_interface() -> None:
    server = build_mcp_server(Settings.from_env())
    tools = await server.list_tools()
    resources = await server.list_resources()
    prompts = await server.list_prompts()
    assert {tool.name for tool in tools} == {
        "get_system_metrics", "get_disk_usage", "list_processes", "read_allowed_log"
    }
    assert [str(resource.uri) for resource in resources] == ["linux://system/summary"]
    assert [prompt.name for prompt in prompts] == ["health_check"]


@pytest.mark.asyncio
async def test_official_client_discovers_core_and_reports_pending_log_tool() -> None:
    async with Client(build_mcp_server(Settings.from_env())) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        prompts = await client.list_prompts()
        assert {tool.name for tool in tools.tools} == {
            "get_system_metrics", "get_disk_usage", "list_processes", "read_allowed_log"
        }
        assert [str(resource.uri) for resource in resources.resources] == [
            "linux://system/summary"
        ]
        assert [prompt.name for prompt in prompts.prompts] == ["health_check"]

        metrics = await client.call_tool("get_system_metrics")
        assert metrics.is_error is not True
        assert metrics.content

        log_result = await client.call_tool("read_allowed_log", {"alias": "ssh"})
        assert log_result.is_error is True
        error_text = " ".join(
            str(getattr(item, "text", "")) for item in log_result.content
        )
        assert "NOT_IMPLEMENTED" in error_text

        summary = await client.read_resource("linux://system/summary")
        assert len(summary.contents) == 1
        summary_text = getattr(summary.contents[0], "text", None)
        assert isinstance(summary_text, str)
        payload = json.loads(summary_text)
        assert "operatingSystem" in payload
        assert "cpuUsagePercent" in payload

        prompt = await client.get_prompt("health_check", {"focus": "overview"})
        prompt_text = getattr(prompt.messages[0].content, "text", None)
        assert isinstance(prompt_text, str)
        assert "read-only" in prompt_text
        assert "Do not call read_allowed_log" in prompt_text


@pytest.mark.asyncio
async def test_mounted_asgi_app_manages_mcp_session_lifespan() -> None:
    app = build_asgi_app(Settings.from_env())
    async with app.router.lifespan_context(app):
        assert len(app.routes) == 2
