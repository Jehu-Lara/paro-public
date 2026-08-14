"""Manejo de errores uniforme de la API.

``DuplicateWithDifferentPayloadError`` (409) y cualquier excepcion no
controlada (500 generico, logueado con detalle en servidor) son los unicos
casos especiales: la validacion de Pydantic ya produce 422 por defecto y no
hace falta reinventarla.
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
    """Convierte un valor a algo serializable en JSON sin pasar por ``float``.

    ``Decimal`` se serializa como string y ``datetime`` como ISO 8601: la
    misma regla que las respuestas Pydantic, para que un 409 no pierda
    precision ni deje pasar un naive por accidente.
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
    """Registra los handlers de errores en ``app``."""
    app.add_exception_handler(
        DuplicateWithDifferentPayloadError, _duplicate_with_different_payload_handler
    )
    app.add_exception_handler(Exception, _generic_exception_handler)
