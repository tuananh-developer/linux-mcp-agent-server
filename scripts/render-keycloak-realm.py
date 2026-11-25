#!/usr/bin/env python3
"""Render private Keycloak bootstrap files without committing generated secrets."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def write_private_json(destination: Path, value: Any) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, destination)
        os.chmod(destination, 0o600)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--user-output", type=Path, required=True)
    parser.add_argument("--credential-output", type=Path, required=True)
    args = parser.parse_args()

    mcp_domain = required_env("MCP_DOMAIN")
    auth_domain = required_env("AUTH_DOMAIN")
    resource_secret = required_env("RESOURCE_SERVER_SECRET")
    agent_secret = required_env("AGENT_CLIENT_SECRET")
    username = required_env("INITIAL_ADMIN_USERNAME")
    password = required_env("INITIAL_ADMIN_PASSWORD")
    email = os.environ.get("INITIAL_ADMIN_EMAIL", "").strip()

    for value in (mcp_domain, auth_domain):
        if (
            not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", value)
            or value.startswith(".")
            or value.endswith(".")
        ):
            raise SystemExit("MCP_DOMAIN and AUTH_DOMAIN must be valid DNS hostnames.")
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,64}", username):
        raise SystemExit("INITIAL_ADMIN_USERNAME must be 3-64 letters, digits, dots, underscores or hyphens.")
    if len(password) < 12:
        raise SystemExit("INITIAL_ADMIN_PASSWORD must contain at least 12 characters.")

    realm: dict[str, Any] = json.loads(args.template.read_text(encoding="utf-8"))
    replacements = {
        "https://mcp.home.arpa": f"https://{mcp_domain}",
        "https://auth.home.arpa": f"https://{auth_domain}",
    }

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, str):
            for old, new in replacements.items():
                value = value.replace(old, new)
            if value == "CHANGE_ME_RESOURCE_SERVER_SECRET":
                return resource_secret
            if value == "CHANGE_ME_AGENT_CLIENT_SECRET":
                return agent_secret
        return value

    realm = walk(realm)
    if "CHANGE_ME_" in json.dumps(realm):
        raise SystemExit("The rendered realm still contains an unreplaced secret placeholder.")

    user: dict[str, Any] = {"username": username, "enabled": True}
    if email:
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise SystemExit("INITIAL_ADMIN_EMAIL must be a valid email address.")
        user["email"] = email
        user["emailVerified"] = True

    write_private_json(args.output, realm)
    write_private_json(args.user_output, user)
    write_private_json(
        args.credential_output,
        {"type": "password", "value": password, "temporary": False},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
