"""Validated, dependency-light environment configuration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class ConfigurationError(ValueError):
    """Raised when an unsafe or incomplete configuration is supplied."""


def _csv(value: str | None, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _require_https_url(name: str, value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
        raise ConfigurationError(f"{name} must be an absolute HTTPS URL without query/fragment")
    return value.rstrip("/")


def _require_loopback_http_url(name: str, value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.query
        or parsed.fragment
        or not parsed.path.endswith("/protocol/openid-connect/token/introspect")
    ):
        raise ConfigurationError(f"{name} must be a loopback Keycloak introspection URL")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str
    auth_mode: str
    host: str
    port: int
    public_url: str
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    issuer_url: str
    introspection_url: str
    resource_uri: str
    introspection_client_id: str
    introspection_client_secret: str
    required_scope: str
    logs_scope: str
    required_audience: str
    allowed_disk_paths: tuple[str, ...]
    allowed_systemd_units: tuple[str, ...]
    systemctl_path: str
    cpu_warning_threshold_percent: float
    memory_warning_threshold_percent: float
    disk_warning_threshold_percent: float
    log_sources_file: Path
    journalctl_path: str
    journalctl_timeout_seconds: float
    max_log_output_bytes: int
    log_level: str
    introspection_cache_ttl_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> Settings:
        auth_mode = os.getenv("AUTH_MODE", "disabled").strip().lower()
        if auth_mode not in {"disabled", "keycloak"}:
            raise ConfigurationError("AUTH_MODE must be 'disabled' or 'keycloak'")

        host = os.getenv("MCP_HOST", "127.0.0.1").strip()
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise ConfigurationError("MCP_HOST must be loopback; expose LAN traffic through Caddy")

        try:
            port = int(os.getenv("MCP_PORT", "3002"))
            timeout = float(os.getenv("JOURNALCTL_TIMEOUT_SECONDS", "1.5"))
            max_bytes = int(os.getenv("MAX_LOG_OUTPUT_BYTES", "65536"))
            cache_ttl = float(os.getenv("MCP_INTROSPECTION_CACHE_TTL_SECONDS", "30.0"))
            cpu_threshold = float(os.getenv("CPU_WARNING_THRESHOLD_PERCENT", "85"))
            memory_threshold = float(os.getenv("MEMORY_WARNING_THRESHOLD_PERCENT", "90"))
            disk_threshold = float(os.getenv("DISK_WARNING_THRESHOLD_PERCENT", "85"))
        except ValueError as exc:
            raise ConfigurationError(
                "MCP_PORT, JOURNALCTL_TIMEOUT_SECONDS, MAX_LOG_OUTPUT_BYTES, MCP_INTROSPECTION_CACHE_TTL_SECONDS and alert thresholds must be numeric"
            ) from exc
        if not 1 <= port <= 65535:
            raise ConfigurationError("MCP_PORT must be between 1 and 65535")
        if not 0.1 <= timeout <= 5.0:
            raise ConfigurationError("JOURNALCTL_TIMEOUT_SECONDS must be between 0.1 and 5")
        if not 1024 <= max_bytes <= 262144:
            raise ConfigurationError("MAX_LOG_OUTPUT_BYTES must be between 1024 and 262144")
        if not 0.0 <= cache_ttl <= 300.0:
            raise ConfigurationError("MCP_INTROSPECTION_CACHE_TTL_SECONDS must be between 0 and 300")
        for name, threshold in (
            ("CPU_WARNING_THRESHOLD_PERCENT", cpu_threshold),
            ("MEMORY_WARNING_THRESHOLD_PERCENT", memory_threshold),
            ("DISK_WARNING_THRESHOLD_PERCENT", disk_threshold),
        ):
            if not 1.0 <= threshold <= 100.0:
                raise ConfigurationError(f"{name} must be between 1 and 100")

        public_url = _require_https_url(
            "MCP_PUBLIC_URL", os.getenv("MCP_PUBLIC_URL", "https://mcp.home.arpa/mcp")
        )
        issuer = _require_https_url(
            "KEYCLOAK_ISSUER_URL",
            os.getenv("KEYCLOAK_ISSUER_URL", "https://auth.home.arpa/realms/linux-agent"),
        )
        introspection_url = _require_loopback_http_url(
            "MCP_INTROSPECTION_URL",
            os.getenv(
                "MCP_INTROSPECTION_URL",
                "http://127.0.0.1:8080/realms/linux-agent/protocol/openid-connect/token/introspect",
            ),
        )
        resource_uri = _require_https_url(
            "MCP_RESOURCE_URI", os.getenv("MCP_RESOURCE_URI", public_url)
        )
        audience = _require_https_url(
            "MCP_REQUIRED_AUDIENCE", os.getenv("MCP_REQUIRED_AUDIENCE", resource_uri)
        )
        if audience != resource_uri:
            raise ConfigurationError(
                "MCP_REQUIRED_AUDIENCE must equal MCP_RESOURCE_URI after normalization"
            )
        allowed_disks = _csv(os.getenv("ALLOWED_DISK_PATHS"), ("/",))
        if not allowed_disks or any(
            not Path(path).is_absolute() or ".." in Path(path).parts for path in allowed_disks
        ):
            raise ConfigurationError("ALLOWED_DISK_PATHS must contain absolute, normalized paths")

        app_env = os.getenv("APP_ENV", "development").strip().lower()
        if app_env not in {"development", "production"}:
            raise ConfigurationError("APP_ENV must be 'development' or 'production'")

        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ConfigurationError("LOG_LEVEL must be a standard Python logging level")

        journalctl_path = os.getenv("JOURNALCTL_PATH", "/usr/bin/journalctl").strip()
        if (
            not journalctl_path
            or not Path(journalctl_path).is_absolute()
            or ".." in Path(journalctl_path).parts
        ):
            raise ConfigurationError("JOURNALCTL_PATH must be an absolute path without traversal")

        systemctl_path = os.getenv("SYSTEMCTL_PATH", "/usr/bin/systemctl").strip()
        if (
            not systemctl_path
            or not Path(systemctl_path).is_absolute()
            or ".." in Path(systemctl_path).parts
        ):
            raise ConfigurationError("SYSTEMCTL_PATH must be an absolute path without traversal")

        allowed_systemd_units = _csv(
            os.getenv("ALLOWED_SYSTEMD_UNITS"),
            ("ssh.service", "cron.service", "systemd-timesyncd.service"),
        )
        if any(
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]{0,127}\.service", unit)
            for unit in allowed_systemd_units
        ):
            raise ConfigurationError("ALLOWED_SYSTEMD_UNITS must contain valid .service unit names")

        settings = cls(
            app_env=app_env,
            auth_mode=auth_mode,
            host=host,
            port=port,
            public_url=public_url,
            allowed_hosts=_csv(
                os.getenv("MCP_ALLOWED_HOSTS"),
                ("127.0.0.1:3002", "localhost:3002", "mcp.home.arpa", "mcp.home.arpa:443"),
            ),
            allowed_origins=_csv(os.getenv("MCP_ALLOWED_ORIGINS")),
            issuer_url=issuer,
            introspection_url=introspection_url,
            resource_uri=resource_uri,
            introspection_client_id=os.getenv("MCP_INTROSPECTION_CLIENT_ID", "").strip(),
            introspection_client_secret=os.getenv("MCP_INTROSPECTION_CLIENT_SECRET", ""),
            required_scope=os.getenv("MCP_REQUIRED_SCOPE", "mcp.read").strip(),
            logs_scope=os.getenv("MCP_LOGS_SCOPE", "mcp.logs.read").strip(),
            required_audience=audience,
            allowed_disk_paths=allowed_disks,
            allowed_systemd_units=allowed_systemd_units,
            systemctl_path=systemctl_path,
            cpu_warning_threshold_percent=cpu_threshold,
            memory_warning_threshold_percent=memory_threshold,
            disk_warning_threshold_percent=disk_threshold,
            log_sources_file=Path(
                os.getenv("LOG_SOURCES_FILE", "config/log-sources.example.json")
            ).expanduser(),
            journalctl_path=journalctl_path,
            journalctl_timeout_seconds=timeout,
            max_log_output_bytes=max_bytes,
            log_level=log_level,
            introspection_cache_ttl_seconds=cache_ttl,
        )
        if auth_mode == "keycloak":
            if not settings.introspection_client_id or not settings.introspection_client_secret:
                raise ConfigurationError(
                    "Keycloak mode requires introspection client ID and secret"
                )
            if not settings.required_scope or not settings.logs_scope:
                raise ConfigurationError("MCP required scopes must not be empty")
        if settings.app_env == "production" and auth_mode != "keycloak":
            raise ConfigurationError("Production mode requires AUTH_MODE=keycloak")
        return settings
