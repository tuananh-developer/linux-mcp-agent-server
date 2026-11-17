from __future__ import annotations

import pytest

from linux_mcp_agent.config import ConfigurationError, Settings


def test_settings_defaults_to_loopback_and_local_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.delenv("MCP_HOST", raising=False)
    settings = Settings.from_env()
    assert settings.auth_mode == "disabled"
    assert settings.host == "127.0.0.1"
    assert settings.port == 3000


def test_settings_rejects_non_loopback_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_HOST", "0.0.0.0")
    with pytest.raises(ConfigurationError):
        Settings.from_env()


def test_production_requires_keycloak(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    with pytest.raises(ConfigurationError):
        Settings.from_env()


def test_introspection_url_must_be_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_INTROSPECTION_URL", "https://evil.example/introspect")
    with pytest.raises(ConfigurationError):
        Settings.from_env()


def test_settings_rejects_unknown_app_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging-ish")
    with pytest.raises(ConfigurationError, match="APP_ENV"):
        Settings.from_env()
