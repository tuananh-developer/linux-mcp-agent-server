"""Serve the dashboard shell. All host data is requested through authenticated MCP."""

from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import Route

_WEB = Path(__file__).with_name("web")
_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    ),
}


async def dashboard_page(_: Request) -> FileResponse:
    return FileResponse(_WEB / "index.html", headers=_HEADERS)


async def dashboard_script(_: Request) -> FileResponse:
    return FileResponse(_WEB / "app.js", media_type="text/javascript", headers=_HEADERS)


async def dashboard_styles(_: Request) -> FileResponse:
    return FileResponse(_WEB / "app.css", media_type="text/css", headers=_HEADERS)


async def dashboard_transport(_: Request) -> FileResponse:
    return FileResponse(_WEB / "mcp-client.mjs", media_type="text/javascript", headers=_HEADERS)


async def agent_script(_: Request) -> FileResponse:
    return FileResponse(_WEB / "agent-ui.js", media_type="text/javascript", headers=_HEADERS)


async def agent_transport(_: Request) -> FileResponse:
    return FileResponse(_WEB / "agent-client.mjs", media_type="text/javascript", headers=_HEADERS)


def dashboard_routes() -> list[Route]:
    return [
        Route("/", dashboard_page, methods=["GET"]),
        Route("/dashboard", dashboard_page, methods=["GET"]),
        Route("/dashboard/assets/agent-ui.js", agent_script, methods=["GET"]),
        Route("/dashboard/assets/agent-client.mjs", agent_transport, methods=["GET"]),
        Route("/dashboard/assets/app.js", dashboard_script, methods=["GET"]),
        Route("/dashboard/assets/app.css", dashboard_styles, methods=["GET"]),
        Route("/dashboard/assets/mcp-client.mjs", dashboard_transport, methods=["GET"]),
    ]
