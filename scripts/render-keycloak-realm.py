#!/usr/bin/env python3
"""Render a first-install Keycloak realm without committing generated secrets."""

from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    mcp_domain = required_env("MCP_DOMAIN")
    auth_domain = required_env("AUTH_DOMAIN")
    resource_secret = required_env("RESOURCE_SERVER_SECRET")
    agent_secret = required_env("AGENT_CLIENT_SECRET")
    username = required_env("INITIAL_ADMIN_USERNAME")
    password = required_env("INITIAL_ADMIN_PASSWORD")
    email = os.environ.get("INITIAL_ADMIN_EMAIL", "").strip()

    for value in (mcp_domain, auth_domain):
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", value) or value.startswith(".") or value.endswith("."):
            raise SystemExit("MCP_DOMAIN and AUTH_DOMAIN must be valid DNS hostnames.")

    realm: dict[str, Any] = json.loads(args.template.read_text(encoding="utf-8"))
    realm["users"] = [
        {
            "username": username,
            "enabled": True,
            "email": email or None,
            "emailVerified": bool(email),
            "credentials": [
                {"type": "password", "value": password, "temporary": False}
            ],
        }
    ]
    realm["users"][0] = {key: value for key, value in realm["users"][0].items() if value is not None}

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
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{args.output.name}.", dir=args.output.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(realm, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, args.output)
        os.chmod(args.output, 0o600)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
