"""Uniform API error handling.

``DuplicateWithDifferentPayloadError`` (409) and any uncontrolled
exception (generic 500, logged with detail server-side) are the only
special cases: Pydantic validation already produces a 422 by default and
there's no need to reinvent it.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from paro.db.exceptions import DuplicateWithDifferentPayloadError

__all__ = ["register_exception_handlers"]

logger = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    """Converts a value to something JSON-serializable without going through ``float``.

    ``Decimal`` is serialized as a string and ``datetime`` as ISO 8601: the
    same rule Pydantic responses follow, so a 409 never loses precision or
    lets a naive datetime slip through by accident.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


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
            "differing_fields": _json_safe(exc.differing_fields),
        },
    )


async def _generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def register_exception_handlers(app: FastAPI) -> None:
    """Registers the error handlers on ``app``."""
    app.add_exception_handler(
        DuplicateWithDifferentPayloadError, _duplicate_with_different_payload_handler
    )
    app.add_exception_handler(Exception, _generic_exception_handler)
