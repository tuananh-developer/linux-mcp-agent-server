"""Application entry point."""

from __future__ import annotations

import logging

import uvicorn

from linux_mcp_agent.config import Settings
from linux_mcp_agent.server import build_asgi_app


def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app = build_asgi_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
