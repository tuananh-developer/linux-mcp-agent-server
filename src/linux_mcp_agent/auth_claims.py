"""Pure validation for RFC 7662 introspection responses."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import Any


def _numeric_date(value: object) -> float | None:
    """Return a finite NumericDate as float, rejecting bools and overflow."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        converted = float(value)
    except (OverflowError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def validate_introspection_payload(
    payload: Mapping[str, Any],
    *,
    issuer: str,
    audience: str,
    required_scope: str,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Return normalized claims for an active token or None when it must be rejected."""
    if payload.get("active") is not True:
        return None
    if payload.get("iss") != issuer:
        return None

    exp = _numeric_date(payload.get("exp"))
    current = time.time() if now is None else now
    if exp is None or not math.isfinite(current) or exp <= current:
        return None

    raw_not_before = payload.get("nbf")
    if raw_not_before is not None:
        not_before = _numeric_date(raw_not_before)
        if not_before is None or not_before > current:
            return None

    raw_audience = payload.get("aud")
    audiences = [raw_audience] if isinstance(raw_audience, str) else raw_audience
    if (
        not isinstance(audiences, list)
        or audience not in audiences
        or not all(isinstance(item, str) for item in audiences)
    ):
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

    return {
        **dict(payload),
        "scopes": scopes,
        "expires_at": int(exp),
        "client_id": client_id,
        "subject": subject,
        "validated_audience": audience,
    }
