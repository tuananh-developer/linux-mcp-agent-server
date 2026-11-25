from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_renderer_injects_domain_secrets_and_initial_user(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "linux-agent-realm.json"
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
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    realm = json.loads(output.read_text(encoding="utf-8"))
    assert realm["realm"] == "linux-agent"
    assert realm["users"][0]["username"] == "first.operator"
    assert realm["users"][0]["credentials"][0]["value"] == "a-strong-test-password"
    assert realm["users"][0]["email"] == "operator@example.test"

    clients = {client["clientId"]: client for client in realm["clients"]}
    assert clients["linux-mcp-resource-server"]["secret"] == "resource-secret-test"
    assert clients["linux-mcp-agent-client"]["secret"] == "agent-secret-test"
    assert clients["linux-mcp-resource-server"]["attributes"]["resource_url"] == (
        "https://observatory.example.test/mcp"
    )
    browser = clients["linux-observatory-browser"]
    assert browser["redirectUris"] == ["https://observatory.example.test/*"]
    assert browser["webOrigins"] == ["https://observatory.example.test"]
    assert output.stat().st_mode & 0o777 == 0o600


def test_renderer_rejects_invalid_hostname(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "realm.json"
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
        ],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "valid DNS hostnames" in result.stderr
    assert not output.exists()
