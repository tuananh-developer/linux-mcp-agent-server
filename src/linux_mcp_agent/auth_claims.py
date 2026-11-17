"""Pure validation for Keycloak RFC 7662 introspection responses."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any


def validate_introspection_payload(
    payload: Mapping[str, Any],
    *,
    issuer: str,
    audience: str,
    required_scope: str,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Return normalized claims for an active token or ``None`` when it must be rejected."""
    if payload.get("active") is not True:
        return None
    if payload.get("iss") != issuer:
        return None

    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool):
        return None
    current = time.time() if now is None else now
    if exp <= current:
        return None

    not_before = payload.get("nbf")
    if not_before is not None and (
        isinstance(not_before, bool)
        or not isinstance(not_before, (int, float))
        or not_before > current
    ):
        return None

    raw_audience = payload.get("aud")
    audiences = [raw_audience] if isinstance(raw_audience, str) else raw_audience
    if not isinstance(audiences, list) or audience not in audiences or not all(isinstance(a, str) for a in audiences):
        return None

    raw_scope = payload.get("scope", "")
    scopes = raw_scope.split() if isinstance(raw_scope, str) else raw_scope
    if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
        return None
    if required_scope not in scopes:
        return None

    client_id = payload.get("client_id")
    subject = payload.get("sub")
    if not isinstance(client_id, str) or not client_id:
        return None
    if subject is not None and not isinstance(subject, str):
        return None

    return {**dict(payload), "scopes": scopes, "expires_at": int(exp), "client_id": client_id, "subject": subject}
