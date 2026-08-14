"""Tipos de columna compartidos entre dialectos.

``domain/intervals.py`` rechaza cualquier ``datetime`` naive con ``ValueError``
(ver ADR: los timestamps siempre son tz-aware en UTC). SQLite no tiene un tipo
de fecha/hora nativo con zona horaria: guarda el valor y, al leerlo, devuelve
un ``datetime`` naive. ``UTCDateTime`` cierra esa brecha en el borde de la
base de datos para que el dominio nunca vea un naive, en ningun dialecto.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """``DateTime`` que normaliza a UTC al escribir y reasigna UTC al leer."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                f"UTCDateTime requiere un datetime tz-aware; se recibio uno naive ({value!r})."
            )
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
