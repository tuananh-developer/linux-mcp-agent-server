from __future__ import annotations

import asyncio
import socket

import pytest
import uvicorn
from mcp import Client

from linux_mcp_agent.config import Settings
from linux_mcp_agent.server import build_asgi_app


@pytest.mark.asyncio
async def test_official_client_uses_real_streamable_http_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the ASGI app over TCP, not the SDK's in-process transport."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        monkeypatch.setenv("MCP_ALLOWED_HOSTS", f"127.0.0.1:{port}")

        app = build_asgi_app(Settings.from_env())
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="critical",
                access_log=False,
                lifespan="on",
            )
        )
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 10
            while not server.started and loop.time() < deadline:
                if server_task.done():
                    await server_task
                    raise AssertionError("Uvicorn exited before the HTTP server became ready")
                await asyncio.sleep(0.01)
            assert server.started, "Uvicorn did not start within 10 seconds"

            async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                tools = await client.list_tools()
                assert {tool.name for tool in tools.tools} == {
                    "get_system_metrics",
                    "get_disk_usage",
                    "list_processes",
                    "read_allowed_log",
                }

                metrics = await client.call_tool("get_system_metrics")
                assert metrics.is_error is not True
                assert metrics.content

                resource = await client.read_resource("linux://system/summary")
                assert len(resource.contents) == 1

                prompt = await client.get_prompt("health_check", {"focus": "overview"})
                assert len(prompt.messages) == 1
        finally:
            server.should_exit = True
            await asyncio.wait_for(server_task, timeout=10)
