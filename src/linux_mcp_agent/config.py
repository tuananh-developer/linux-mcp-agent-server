"""Minimal runtime configuration for the MCP core."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when runtime configuration is invalid or unsafe."""


def _csv(value: str | None, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings required by the local, loopback-only MCP core."""

    host: str
    port: int
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    allowed_disk_paths: tuple[str, ...]
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        host = os.getenv("MCP_HOST", "127.0.0.1").strip()
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise ConfigurationError("MCP_HOST must be loopback on the handoff branch")

        try:
            port = int(os.getenv("MCP_PORT", "3000"))
        except ValueError as exc:
            raise ConfigurationError("MCP_PORT must be an integer") from exc
        if not 1 <= port <= 65535:
            raise ConfigurationError("MCP_PORT must be between 1 and 65535")

        allowed_disks = _csv(os.getenv("ALLOWED_DISK_PATHS"), ("/",))
        if not allowed_disks or any(
            not Path(path).is_absolute() or ".." in Path(path).parts
            for path in allowed_disks
        ):
            raise ConfigurationError("ALLOWED_DISK_PATHS must contain absolute paths without traversal")

        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ConfigurationError("LOG_LEVEL must be a standard Python logging level")

        return cls(
            host=host,
            port=port,
            allowed_hosts=_csv(
                os.getenv("MCP_ALLOWED_HOSTS"),
                ("127.0.0.1:3000", "localhost:3000"),
            ),
            allowed_origins=_csv(os.getenv("MCP_ALLOWED_ORIGINS")),
            allowed_disk_paths=allowed_disks,
            log_level=log_level,
        )
