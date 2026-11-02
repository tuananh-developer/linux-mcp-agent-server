"""Keycloak token introspection adapter for the MCP SDK resource-server interface."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from mcp.server.auth.provider import AccessToken, TokenVerifier

from linux_mcp_agent.auth_claims import validate_introspection_payload
from linux_mcp_agent.config import Settings

logger = logging.getLogger(__name__)


class KeycloakIntrospectionVerifier(TokenVerifier):
    """Verify access tokens by calling Keycloak's protected introspection endpoint."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._endpoint = settings.introspection_url
        self._opener = build_opener(ProxyHandler({}))

    async def verify_token(self, token: str) -> AccessToken | None:
        return await asyncio.to_thread(self._verify_sync, token)

    def _verify_sync(self, token: str) -> AccessToken | None:
        credentials = f"{self._settings.introspection_client_id}:{self._settings.introspection_client_secret}".encode()
        basic = base64.b64encode(credentials).decode("ascii")
        body = urlencode({"token": token, "token_type_hint": "access_token"}).encode("ascii")
        request = Request(
            self._endpoint,
            data=body,
            headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=2.0) as response:
                payload = json.loads(response.read(65536).decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("Keycloak token introspection failed")
            return None

        if not isinstance(payload, dict):
            return None
        claims = validate_introspection_payload(
            payload,
            issuer=self._settings.issuer_url,
            audience=self._settings.required_audience,
            required_scope=self._settings.required_scope,
        )
        if claims is None:
            return None
        return AccessToken(
            token=token,
            client_id=claims["client_id"],
            scopes=claims["scopes"],
            expires_at=claims["expires_at"],
            resource=self._settings.resource_uri,
            subject=claims["subject"],
            claims={key: value for key, value in claims.items() if key not in {"scopes", "expires_at", "client_id", "subject"}},
        )
