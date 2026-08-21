"""Uniform API error handling.

``DuplicateWithDifferentPayloadError``, ``StaleUpdateError`` (both 409) and
any uncontrolled exception (generic 500, logged with detail server-side)
are the only special cases: Pydantic validation already produces a 422 by
default and there's no need to reinvent it.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from paro.db.exceptions import DuplicateWithDifferentPayloadError, StaleUpdateError
from paro.json_safe import json_safe

__all__ = ["register_exception_handlers"]

logger = logging.getLogger(__name__)


async def _duplicate_with_different_payload_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    assert isinstance(exc, DuplicateWithDifferentPayloadError)
    return JSONResponse(
        status_code=409,
        content={
            "error": "duplicate_with_different_payload",
            "entity": exc.entity,
            "source": exc.source,
            "external_id": exc.external_id,
            "differing_fields": json_safe(exc.differing_fields),
        },
    )


async def _stale_update_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StaleUpdateError)
    return JSONResponse(
        status_code=409,
        content={
            "error": "stale_update",
            "entity": exc.entity,
            "id": exc.id,
            "expected_updated_at": json_safe(exc.expected_updated_at),
            "actual_updated_at": json_safe(exc.actual_updated_at),
        },
    )


async def _generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Exception messages and tracebacks may contain SQL-bound values or other
    # request-derived payload data.  Log only a fixed diagnostic allowlist.
    logger.error(
        "Unhandled exception",
        extra={
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def register_exception_handlers(app: FastAPI) -> None:
    """Registers the error handlers on ``app``."""
    app.add_exception_handler(
        DuplicateWithDifferentPayloadError, _duplicate_with_different_payload_handler
    )
    app.add_exception_handler(StaleUpdateError, _stale_update_handler)
    app.add_exception_handler(Exception, _generic_exception_handler)
