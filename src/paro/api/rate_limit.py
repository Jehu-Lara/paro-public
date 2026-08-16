"""Shared rate limiter for write endpoints.

In-memory backend: sufficient for a single Render free-tier instance,
where there's no shared state to coordinate across processes anyway.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

__all__ = ["limiter"]

limiter = Limiter(key_func=get_remote_address)
