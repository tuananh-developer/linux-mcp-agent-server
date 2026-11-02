from __future__ import annotations

import pytest

from linux_mcp_agent.config import ConfigurationError, Settings


def test_settings_default_to_local_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("MCP_HOST", "MCP_PORT", "MCP_ALLOWED_HOSTS", "MCP_ALLOWED_ORIGINS", "ALLOWED_DISK_PATHS", "LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings.from_env()
    assert settings.host == "127.0.0.1"
    assert settings.port == 3000
    assert settings.allowed_hosts == ("127.0.0.1:3000", "localhost:3000")
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
