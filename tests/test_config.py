from __future__ import annotations

import pytest

from linux_mcp_agent.config import ConfigurationError, Settings


@pytest.mark.parametrize("audience", ["https://mcp.home.arpa/mcp", "https://mcp.home.arpa/mcp/"])
def test_accepts_matching_resource_and_audience(
    monkeypatch: pytest.MonkeyPatch, audience: str,
) -> None:
    monkeypatch.setenv("MCP_RESOURCE_URI", "https://mcp.home.arpa/mcp/")
    monkeypatch.setenv("MCP_REQUIRED_AUDIENCE", audience)
    settings = Settings.from_env()
    assert settings.resource_uri == settings.required_audience == "https://mcp.home.arpa/mcp"


@pytest.mark.parametrize("audience", ["https://other.example/mcp", "https://mcp.home.arpa/other"])
def test_rejects_mismatching_resource_and_audience(
    monkeypatch: pytest.MonkeyPatch, audience: str,
) -> None:
    monkeypatch.setenv("MCP_RESOURCE_URI", "https://mcp.home.arpa/mcp")
    monkeypatch.setenv("MCP_REQUIRED_AUDIENCE", audience)
    with pytest.raises(ConfigurationError, match="MCP_REQUIRED_AUDIENCE must equal MCP_RESOURCE_URI"):
        Settings.from_env()


def test_audience_defaults_to_normalized_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_RESOURCE_URI", "https://custom.example/mcp/")
    monkeypatch.delenv("MCP_REQUIRED_AUDIENCE", raising=False)
    settings = Settings.from_env()
    assert settings.required_audience == settings.resource_uri == "https://custom.example/mcp"


def test_settings_default_to_local_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "APP_ENV",
        "AUTH_MODE",
        "MCP_HOST",
        "MCP_PORT",
        "MCP_ALLOWED_HOSTS",
        "MCP_ALLOWED_ORIGINS",
        "ALLOWED_DISK_PATHS",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = Settings.from_env()
    assert settings.auth_mode == "disabled"
    assert settings.host == "127.0.0.1"
    assert settings.port == 3000
    assert "127.0.0.1:3000" in settings.allowed_hosts
    assert "localhost:3000" in settings.allowed_hosts
    assert settings.allowed_disk_paths == ("/",)
    assert settings.log_level == "INFO"


def test_rejects_non_loopback_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_HOST", "0.0.0.0")
    with pytest.raises(ConfigurationError, match="loopback"):
        Settings.from_env()


@pytest.mark.parametrize("port", ["0", "65536", "-1", "invalid"])
def test_rejects_invalid_port(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    monkeypatch.setenv("MCP_PORT", port)
    with pytest.raises(ConfigurationError, match="MCP_PORT"):
        Settings.from_env()


@pytest.mark.parametrize("paths", ["", "relative/path", "/safe/../etc"])
def test_rejects_invalid_disk_paths(monkeypatch: pytest.MonkeyPatch, paths: str) -> None:
    monkeypatch.setenv("ALLOWED_DISK_PATHS", paths)
    with pytest.raises(ConfigurationError, match="ALLOWED_DISK_PATHS"):
        Settings.from_env()


def test_parses_hosts_origins_and_disk_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "localhost:3000, mcp.example.test")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://agent.example.test")
    monkeypatch.setenv("ALLOWED_DISK_PATHS", "/,/home")
    settings = Settings.from_env()
    assert settings.allowed_hosts == ("localhost:3000", "mcp.example.test")
    assert settings.allowed_origins == ("https://agent.example.test",)
    assert settings.allowed_disk_paths == ("/", "/home")


def test_rejects_unknown_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
    with pytest.raises(ConfigurationError, match="LOG_LEVEL"):
        Settings.from_env()


def test_production_requires_keycloak(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    with pytest.raises(ConfigurationError, match="AUTH_MODE=keycloak"):
        Settings.from_env()


def test_keycloak_mode_requires_client_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "keycloak")
    monkeypatch.setenv("MCP_INTROSPECTION_CLIENT_ID", "")
    monkeypatch.setenv("MCP_INTROSPECTION_CLIENT_SECRET", "")
    with pytest.raises(ConfigurationError, match="introspection client ID and secret"):
        Settings.from_env()


def test_introspection_url_must_be_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_INTROSPECTION_URL", "https://evil.example/protocol/openid-connect/token/introspect")
    with pytest.raises(ConfigurationError, match="MCP_INTROSPECTION_URL"):
        Settings.from_env()


def test_settings_rejects_unknown_app_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging-ish")
    with pytest.raises(ConfigurationError, match="APP_ENV"):
        Settings.from_env()


@pytest.mark.parametrize("bad_path", ["journalctl", "/usr/bin/../bin/journalctl"])
def test_rejects_invalid_journalctl_path(
    monkeypatch: pytest.MonkeyPatch,
    bad_path: str,
) -> None:
    monkeypatch.setenv("JOURNALCTL_PATH", bad_path)
    with pytest.raises(ConfigurationError, match="JOURNALCTL_PATH"):
        Settings.from_env()


def test_settings_parses_cache_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_INTROSPECTION_CACHE_TTL_SECONDS", "45.5")
    settings = Settings.from_env()
    assert settings.introspection_cache_ttl_seconds == 45.5


@pytest.mark.parametrize("bad_ttl", ["-1", "301", "not-a-number"])
def test_settings_rejects_invalid_cache_ttl(
    monkeypatch: pytest.MonkeyPatch,
    bad_ttl: str,
) -> None:
    monkeypatch.setenv("MCP_INTROSPECTION_CACHE_TTL_SECONDS", bad_ttl)
    with pytest.raises(ConfigurationError, match="MCP_INTROSPECTION_CACHE_TTL_SECONDS"):
        Settings.from_env()

