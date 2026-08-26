"""API-key gate for write endpoints (docs/adr/0005-optional-api-key-authentication.md).

Local and other non-production environments remain fail-open when
``PARO_API_KEY`` is unset. Production is fail-closed and refuses writes
when the key is missing or blank.
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request

from paro.config import get_settings

__all__ = ["API_KEY_HEADER", "production_api_key_missing", "require_api_key"]

API_KEY_HEADER = "X-API-Key"


def production_api_key_missing() -> bool:
    """Whether production is missing the API key required for writes."""
    settings = get_settings()
    return settings.env.casefold() == "production" and not (settings.api_key or "").strip()


def require_api_key(request: Request) -> None:
    """Raises 401 unless the request's ``X-API-Key`` header matches
    ``PARO_API_KEY``. Missing keys are allowed only outside production.
    ``secrets.compare_digest`` avoids leaking the key through response-
    timing differences, same rationale as the trusted-ingest token
    comparison.
    """
    settings = get_settings()
    key = settings.api_key
    if not (key or "").strip():
        if settings.env.casefold() == "production":
            raise HTTPException(status_code=503, detail="service authentication is not configured")
        return
    assert key is not None
    header_value = request.headers.get(API_KEY_HEADER)
    if header_value is None or not secrets.compare_digest(header_value, key):
        raise HTTPException(status_code=401, detail="missing or invalid API key")
