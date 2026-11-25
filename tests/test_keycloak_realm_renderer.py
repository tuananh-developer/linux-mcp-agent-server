from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_renderer_injects_domain_secrets_and_initial_user(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "linux-agent-realm.json"
    user_output = tmp_path / "operator.json"
    credential_output = tmp_path / "operator-password.json"
    env = {
        **os.environ,
        "MCP_DOMAIN": "observatory.example.test",
        "AUTH_DOMAIN": "identity.example.test",
        "RESOURCE_SERVER_SECRET": "resource-secret-test",
        "AGENT_CLIENT_SECRET": "agent-secret-test",
        "INITIAL_ADMIN_USERNAME": "first.operator",
        "INITIAL_ADMIN_PASSWORD": "a-strong-test-password",
        "INITIAL_ADMIN_EMAIL": "operator@example.test",
    }
    subprocess.run(
        [
            sys.executable,
            str(root / "scripts/render-keycloak-realm.py"),
            "--template",
            str(root / "deploy/keycloak/realm-linux-agent.example.json"),
            "--output",
            str(output),
            "--user-output",
            str(user_output),
            "--credential-output",
            str(credential_output),
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    realm = json.loads(output.read_text(encoding="utf-8"))
    assert realm["realm"] == "linux-agent"
    user = json.loads(user_output.read_text(encoding="utf-8"))
    credential = json.loads(credential_output.read_text(encoding="utf-8"))
    assert user == {
        "username": "first.operator",
        "enabled": True,
        "email": "operator@example.test",
        "emailVerified": True,
    }
    assert credential == {
        "type": "password",
        "value": "a-strong-test-password",
        "temporary": False,
    }
    assert "users" not in realm
    assert output.stat().st_mode & 0o777 == 0o600
    assert user_output.stat().st_mode & 0o777 == 0o600
    assert credential_output.stat().st_mode & 0o777 == 0o600

    clients = {client["clientId"]: client for client in realm["clients"]}
    assert clients["linux-mcp-resource-server"]["secret"] == "resource-secret-test"
    assert clients["linux-mcp-agent-client"]["secret"] == "agent-secret-test"
    assert clients["linux-mcp-resource-server"]["attributes"]["resource_url"] == (
        "https://observatory.example.test/mcp"
    )
    browser = clients["linux-observatory-browser"]
    assert browser["redirectUris"] == ["https://observatory.example.test/*"]
    assert browser["webOrigins"] == ["https://observatory.example.test"]
    assert {"basic", "mcp.read"} <= set(browser["defaultClientScopes"])


def test_renderer_rejects_invalid_hostname(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "realm.json"
    user_output = tmp_path / "user.json"
    credential_output = tmp_path / "credential.json"
    env = {
        **os.environ,
        "MCP_DOMAIN": "https://unsafe.example",
        "AUTH_DOMAIN": "auth.example.test",
        "RESOURCE_SERVER_SECRET": "resource-secret-test",
        "AGENT_CLIENT_SECRET": "agent-secret-test",
        "INITIAL_ADMIN_USERNAME": "operator",
        "INITIAL_ADMIN_PASSWORD": "strong-test-password",
    }
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/render-keycloak-realm.py"),
            "--template",
            str(root / "deploy/keycloak/realm-linux-agent.example.json"),
            "--output",
            str(output),
            "--user-output",
            str(user_output),
            "--credential-output",
            str(credential_output),
        ],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "valid DNS hostnames" in result.stderr
    assert not output.exists()

def test_browser_client_setup_attaches_basic_scope_for_existing_realms() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts/configure-browser-client.sh").read_text(encoding="utf-8")

    # The startup configurator must repair already-imported realms as well as
    # fresh imports; basic contains Keycloak's Subject (sub) mapper.
    assert "for SCOPE_NAME in basic mcp.read mcp.logs.read; do" in script
    assert "RELATION=default-client-scopes" in script
    assert "basic + mcp.read default" in script
