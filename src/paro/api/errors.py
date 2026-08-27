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
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from paro.db.exceptions import DuplicateWithDifferentPayloadError, StaleUpdateError
from paro.json_safe import json_safe

__all__ = ["SECURITY_HEADERS", "register_exception_handlers"]

logger = logging.getLogger(__name__)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


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
            "differing_fields": sorted(exc.differing_fields),
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


class _UnhandledExceptionBoundary:
    """Stops unhandled exceptions before an ASGI server can log their values."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception as exc:
            logger.error(
                "Unhandled exception",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "exception_type": type(exc).__name__,
                },
            )
            if not response_started:
                response = JSONResponse(
                    status_code=500,
                    content={"detail": "Internal server error"},
                    headers=SECURITY_HEADERS,
                )
                await response(scope, receive, send)


def register_exception_handlers(app: FastAPI) -> None:
    """Registers the error handlers on ``app``."""
    app.add_exception_handler(
        DuplicateWithDifferentPayloadError, _duplicate_with_different_payload_handler
    )
    app.add_exception_handler(StaleUpdateError, _stale_update_handler)
    app.add_middleware(_UnhandledExceptionBoundary)
