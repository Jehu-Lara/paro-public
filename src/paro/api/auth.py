"""Optional API-key gate for write endpoints (docs/adr/0005-optional-api-key-authentication.md).

Unset ``PARO_API_KEY`` (the default) makes ``require_api_key`` a no-op --
every write endpoint stays exactly as open as it is today, including on
the live demo, unless an operator deliberately configures a key.
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request

from paro.config import get_settings

__all__ = ["API_KEY_HEADER", "require_api_key"]

API_KEY_HEADER = "X-API-Key"


def require_api_key(request: Request) -> None:
    """Raises 401 unless the request's ``X-API-Key`` header matches
    ``PARO_API_KEY``. No-op (returns without raising) when the setting is
    unset -- same "unset = no effect" contract as
    ``paro.api.rate_limit.is_trusted_ingest``. ``secrets.compare_digest``
    avoids leaking the key through response-timing differences, same
    rationale as the trusted-ingest token comparison.
    """
    key = get_settings().api_key
    if not key:
        return
    header_value = request.headers.get(API_KEY_HEADER)
    if header_value is None or not secrets.compare_digest(header_value, key):
        raise HTTPException(status_code=401, detail="missing or invalid API key")
