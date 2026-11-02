from __future__ import annotations

from linux_mcp_agent.auth_claims import validate_introspection_payload


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


def validate(payload: dict[str, object]):
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


def test_rejects_missing_required_scope() -> None:
    payload = valid_payload()
    payload["scope"] = "mcp.logs.read"
    assert validate(payload) is None
