from __future__ import annotations

import pytest

from linux_mcp_agent.config import Settings
from linux_mcp_agent.server import build_mcp_server


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
