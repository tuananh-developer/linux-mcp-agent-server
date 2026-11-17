"""Keycloak token introspection adapter for the MCP SDK resource-server interface."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import threading
import time
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from mcp.server.auth.provider import AccessToken, TokenVerifier

from linux_mcp_agent.auth_claims import validate_introspection_payload
from linux_mcp_agent.config import Settings

logger = logging.getLogger(__name__)


class KeycloakIntrospectionVerifier(TokenVerifier):
    """Verify access tokens by calling Keycloak's protected introspection endpoint with TTL caching."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._endpoint = settings.introspection_url
        self._opener = build_opener(ProxyHandler({}))
        self._cache: dict[str, tuple[AccessToken, float]] = {}
        self._cache_lock = threading.Lock()
        self._max_cache_entries = 1024

    def _get_cached(self, token: str) -> AccessToken | None:
        if self._settings.introspection_cache_ttl_seconds <= 0.0:
            return None
        token_key = hashlib.sha256(token.encode("ascii")).hexdigest()
        now = time.monotonic()
        with self._cache_lock:
            entry = self._cache.get(token_key)
            if entry is not None:
                access_token, expires_at = entry
                if now < expires_at:
                    return access_token
                del self._cache[token_key]
        return None

    def _put_cached(self, token: str, access_token: AccessToken, exp_epoch: int) -> None:
        ttl = self._settings.introspection_cache_ttl_seconds
        if ttl <= 0.0:
            return
        remaining_token_lifetime = max(0.0, exp_epoch - time.time())
        effective_ttl = min(ttl, remaining_token_lifetime)
        if effective_ttl <= 0.0:
            return

        token_key = hashlib.sha256(token.encode("ascii")).hexdigest()
        now = time.monotonic()
        expires_at = now + effective_ttl
        with self._cache_lock:
            if len(self._cache) >= self._max_cache_entries:
                expired_keys = [k for k, (_, exp) in self._cache.items() if now >= exp]
                for k in expired_keys:
                    del self._cache[k]
                if len(self._cache) >= self._max_cache_entries:
                    self._cache.pop(next(iter(self._cache)))
            self._cache[token_key] = (access_token, expires_at)

    async def verify_token(self, token: str) -> AccessToken | None:
        if not 1 <= len(token) <= 8192 or any(ord(ch) <= 32 or ord(ch) == 127 for ch in token):
            return None
        cached = self._get_cached(token)
        if cached is not None:
            return cached
        return await asyncio.to_thread(self._verify_sync, token)

    def _verify_sync(self, token: str) -> AccessToken | None:
        cached = self._get_cached(token)
        if cached is not None:
            return cached
        credentials = (
            f"{self._settings.introspection_client_id}:"
            f"{self._settings.introspection_client_secret}"
        ).encode()
        basic = base64.b64encode(credentials).decode("ascii")
        body = urlencode({"token": token, "token_type_hint": "access_token"}).encode("ascii")
        request = Request(
            self._endpoint,
            data=body,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=2.0) as response:
                payload_object: object = json.loads(response.read(65536).decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("Keycloak token introspection failed")
            return None

        if (
            not isinstance(payload_object, dict)
            or not all(isinstance(key, str) for key in payload_object)
        ):
            return None
        payload = cast(dict[str, Any], payload_object)
        claims = validate_introspection_payload(
            payload,
            issuer=self._settings.issuer_url,
            audience=self._settings.required_audience,
            required_scope=self._settings.required_scope,
        )
        if claims is None:
            return None
        validated_resource = str(claims.get("validated_audience") or self._settings.resource_uri)
        access_token = AccessToken(
            token=token,
            client_id=claims["client_id"],
            scopes=claims["scopes"],
            expires_at=claims["expires_at"],
            resource=validated_resource,
            subject=claims["subject"],
            claims={
                key: value
                for key, value in claims.items()
                if key not in {"scopes", "expires_at", "client_id", "subject", "validated_audience"}
            },
        )
        self._put_cached(token, access_token, claims["expires_at"])
        return access_token
