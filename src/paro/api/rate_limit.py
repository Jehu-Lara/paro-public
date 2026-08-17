"""Shared rate limiter for write endpoints.

In-memory backend: sufficient for a single Render free-tier instance,
where there's no shared state to coordinate across processes anyway.
"""

from __future__ import annotations

import secrets

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from paro.config import get_settings

__all__ = ["TRUSTED_INGEST_HEADER", "is_trusted_ingest", "limiter"]

TRUSTED_INGEST_HEADER = "X-Paro-Trusted-Ingest"


def is_trusted_ingest(request: Request) -> bool:
    """Exempts a request from rate limiting via a trusted-ingest token.

    Unset ``PARO_TRUSTED_INGEST_TOKEN`` (the default) makes this always
    ``False`` -- no exemption possible until an operator opts in.
    ``secrets.compare_digest`` avoids leaking the token through response-
    timing differences: this is a credential comparison even though the
    caller is an internal trusted client, not a third party.
    """
    token = get_settings().trusted_ingest_token
    if not token:
        return False
    header_value = request.headers.get(TRUSTED_INGEST_HEADER)
    if header_value is None:
        return False
    return secrets.compare_digest(header_value, token)


limiter = Limiter(key_func=get_remote_address)
