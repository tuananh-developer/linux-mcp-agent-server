from __future__ import annotations

import io
import json
from typing import Any
from urllib.error import URLError

import pytest

from linux_mcp_agent.auth import KeycloakIntrospectionVerifier
from linux_mcp_agent.auth_claims import validate_introspection_payload
from linux_mcp_agent.config import Settings


def valid_payload() -> dict[str, object]:
    return {
        "active": True,
        "iss": "https://auth.home.arpa/realms/linux-agent",
        "aud": ["https://mcp.home.arpa/mcp"],
        "exp": 2_000_000_000,
        "scope": "mcp.read mcp.logs.read",
        "client_id": "linux-mcp-agent-client",
        "sub": "service-account-linux-mcp-agent-client",
    }


def validate(payload: dict[str, object]) -> dict[str, Any] | None:
    return validate_introspection_payload(
        payload,
        issuer="https://auth.home.arpa/realms/linux-agent",
        audience="https://mcp.home.arpa/mcp",
        required_scope="mcp.read",
        now=1_900_000_000,
    )


def test_accepts_active_token_with_exact_issuer_audience_and_scope() -> None:
    result = validate(valid_payload())
    assert result is not None
    assert result["client_id"] == "linux-mcp-agent-client"
    assert "mcp.read" in result["scopes"]


def test_accepts_string_audience_claim() -> None:
    payload = valid_payload()
    payload["aud"] = "https://mcp.home.arpa/mcp"
    result = validate(payload)
    assert result is not None


def test_rejects_inactive_token() -> None:
    payload = valid_payload()
    payload["active"] = False
    assert validate(payload) is None


def test_rejects_wrong_audience() -> None:
    payload = valid_payload()
    payload["aud"] = ["https://other.example/mcp"]
    assert validate(payload) is None


def test_rejects_wrong_issuer() -> None:
    payload = valid_payload()
    payload["iss"] = "https://attacker.example/realms/linux-agent"
    assert validate(payload) is None


def test_rejects_expired_or_missing_expiry() -> None:
    payload = valid_payload()
    payload["exp"] = 1_899_999_999
    assert validate(payload) is None
    payload.pop("exp")
    assert validate(payload) is None


def test_rejects_future_not_before() -> None:
    payload = valid_payload()
    payload["nbf"] = 1_900_000_001
    assert validate(payload) is None


def test_rejects_missing_required_scope() -> None:
    payload = valid_payload()
    payload["scope"] = "mcp.logs.read"
    assert validate(payload) is None


def test_rejects_missing_client_id() -> None:
    payload = valid_payload()
    payload["client_id"] = ""
    assert validate(payload) is None


@pytest.mark.asyncio
async def test_keycloak_introspection_verifier_accepts_valid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "keycloak")
    monkeypatch.setenv("MCP_INTROSPECTION_CLIENT_ID", "linux-mcp-resource-server")
    monkeypatch.setenv("MCP_INTROSPECTION_CLIENT_SECRET", "test-secret")
    settings = Settings.from_env()

    payload = valid_payload()
    payload["exp"] = 9_999_999_999

    class FakeResponse(io.BytesIO):
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    class FakeOpener:
        def open(self, _request: object, timeout: float = 2.0) -> FakeResponse:
            assert timeout == 2.0
            return FakeResponse(json.dumps(payload).encode("utf-8"))

    def fake_build_opener(*_args: object) -> FakeOpener:
        return FakeOpener()

    monkeypatch.setattr("linux_mcp_agent.auth.build_opener", fake_build_opener)
    verifier = KeycloakIntrospectionVerifier(settings)
    token = await verifier.verify_token("opaque-or-jwt-token")
    assert token is not None
    assert token.client_id == "linux-mcp-agent-client"
    assert token.resource == "https://mcp.home.arpa/mcp"
    assert "mcp.read" in token.scopes
    assert "mcp.logs.read" in token.scopes


@pytest.mark.asyncio
async def test_keycloak_introspection_verifier_fails_closed_on_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "keycloak")
    monkeypatch.setenv("MCP_INTROSPECTION_CLIENT_ID", "linux-mcp-resource-server")
    monkeypatch.setenv("MCP_INTROSPECTION_CLIENT_SECRET", "test-secret")
    settings = Settings.from_env()

    class FailingOpener:
        def open(self, _request: object, timeout: float = 2.0) -> object:
            raise URLError("connection refused")

    def failing_build_opener(*_args: object) -> FailingOpener:
        return FailingOpener()

    monkeypatch.setattr("linux_mcp_agent.auth.build_opener", failing_build_opener)
    verifier = KeycloakIntrospectionVerifier(settings)
    assert await verifier.verify_token("any-token") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_token", ["", "has space", "line\nbreak", "x" * 8193])
async def test_keycloak_introspection_verifier_rejects_malformed_tokens_without_network(
    monkeypatch: pytest.MonkeyPatch,
    bad_token: str,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "keycloak")
    monkeypatch.setenv("MCP_INTROSPECTION_CLIENT_ID", "linux-mcp-resource-server")
    monkeypatch.setenv("MCP_INTROSPECTION_CLIENT_SECRET", "test-secret")
    settings = Settings.from_env()
    called = False

    class UnreachableOpener:
        def open(self, _request: object, timeout: float = 2.0) -> object:
            nonlocal called
            called = True
            raise AssertionError("Network should not be called for malformed token")

    def unreachable_build_opener(*_args: object) -> UnreachableOpener:
        return UnreachableOpener()

    monkeypatch.setattr("linux_mcp_agent.auth.build_opener", unreachable_build_opener)
    verifier = KeycloakIntrospectionVerifier(settings)
    assert await verifier.verify_token(bad_token) is None
    assert called is False


def test_keycloak_realm_template_has_expected_clients_scopes_and_placeholders() -> None:
    from pathlib import Path

    realm_path = Path("deploy/keycloak/realm-linux-agent.example.json")
    realm_data = json.loads(realm_path.read_text(encoding="utf-8"))
    assert realm_data["realm"] == "linux-agent"
    scopes = {scope["name"] for scope in realm_data["clientScopes"]}
    assert {"mcp.read", "mcp.logs.read"} <= scopes
    clients = {client["clientId"]: client for client in realm_data["clients"]}
    assert (
        clients["linux-mcp-resource-server"]["attributes"]["resource_url"]
        == "https://mcp.home.arpa/mcp"
    )
    assert str(clients["linux-mcp-resource-server"]["secret"]).startswith("CHANGE_ME_")
    assert str(clients["linux-mcp-agent-client"]["secret"]).startswith("CHANGE_ME_")
