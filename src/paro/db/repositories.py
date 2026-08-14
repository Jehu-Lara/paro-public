"""Repositorios con idempotencia real por ``(source, external_id)``.

Sigue el patron de "idempotent requests" de Stripe: la misma clave con el
mismo payload devuelve la fila existente sin excepcion; la misma clave con un
payload distinto lanza :class:`DuplicateWithDifferentPayloadError` en vez de
duplicar la fila o dejar pasar el conflicto en silencio.

La comparacion de payload cubre **todos** los campos de negocio del modelo
(no solo un subconjunto): compararlos a medias haria que un cambio real en un
campo no comparado se tratara como si fuera el mismo dato.

Sin logica de OEE aqui: estos repositorios solo persisten filas.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from paro.db.exceptions import DuplicateWithDifferentPayloadError
from paro.db.models import DowntimeEvent, ProductionRecord

__all__ = ["create_downtime_event", "create_production_record"]


def _is_unique_violation(
    exc: IntegrityError, *, constraint_name: str, column_names: tuple[str, ...]
) -> bool:
    """``True`` si ``exc`` es la violacion UNIQUE de ``constraint_name``.

    Evita que un ``except IntegrityError`` generico se trague otro tipo de
    violacion de integridad (un CHECK o una FK) y lo confunda con un
    duplicado de clave de idempotencia. El texto del error es especifico de
    cada driver -- psycopg (PostgreSQL) y sqlite3 no usan el mismo formato,
    ver ejemplos abajo -- asi que se reconocen ambos en vez de asumir uno
    solo. ``constraint_name`` es estable entre dialectos porque
    ``paro.db.base.NAMING_CONVENTION`` lo fija en la definicion del modelo.

    PostgreSQL/psycopg: ``...unique constraint "uq_downtime_event_source"``
    SQLite: ``UNIQUE constraint failed: downtime_event.source, downtime_event.external_id``
    """
    message = str(exc.orig)
    if f'"{constraint_name}"' in message:
        return True
    return "UNIQUE constraint failed" in message and all(name in message for name in column_names)


def _differing_fields(pairs: dict[str, tuple[Any, Any]]) -> dict[str, tuple[Any, Any]]:
    return {name: pair for name, pair in pairs.items() if pair[0] != pair[1]}


def create_downtime_event(
    session: Session,
    *,
    line_id: int,
    reason_id: int,
    started_at: datetime,
    is_planned: bool,
    machine_id: int | None = None,
    ended_at: datetime | None = None,
    operator_note: str | None = None,
    source: str | None = None,
    external_id: str | None = None,
) -> tuple[DowntimeEvent, bool]:
    """Inserta un evento de paro; devuelve ``(evento, was_created)``.

    Sin ``source`` y ``external_id`` no hay clave de idempotencia posible:
    se inserta directo y ``was_created`` siempre es ``True``. Con ambos, un
    choque de UNIQUE se resuelve comparando el payload de negocio completo
    contra la fila existente.
    """
    event = DowntimeEvent(
        line_id=line_id,
        machine_id=machine_id,
        started_at=started_at,
        ended_at=ended_at,
        reason_id=reason_id,
        is_planned=is_planned,
        operator_note=operator_note,
        source=source,
        external_id=external_id,
    )
    if source is None or external_id is None:
        session.add(event)
        session.flush()
        return event, True

    try:
        with session.begin_nested():
            session.add(event)
            session.flush()
    except IntegrityError as exc:
        if not _is_unique_violation(
            exc, constraint_name="uq_downtime_event_source", column_names=("source", "external_id")
        ):
            raise
        existing = session.execute(
            select(DowntimeEvent).where(
                DowntimeEvent.source == source, DowntimeEvent.external_id == external_id
            )
        ).scalar_one()
        differences = _differing_fields(
            {
                "line_id": (existing.line_id, line_id),
                "machine_id": (existing.machine_id, machine_id),
                "started_at": (existing.started_at, started_at),
                "ended_at": (existing.ended_at, ended_at),
                "reason_id": (existing.reason_id, reason_id),
                "is_planned": (existing.is_planned, is_planned),
                "operator_note": (existing.operator_note, operator_note),
            }
        )
        if differences:
            raise DuplicateWithDifferentPayloadError(
                entity="downtime_event",
                source=source,
                external_id=external_id,
                differing_fields=differences,
            ) from exc
        return existing, False
    return event, True


def create_production_record(
    session: Session,
    *,
    line_id: int,
    interval_start: datetime,
    interval_end: datetime,
    total_count: int,
    good_count: int,
    ideal_cycle_time_seconds: Decimal,
    source: str | None = None,
    external_id: str | None = None,
) -> tuple[ProductionRecord, bool]:
    """Inserta un registro de produccion; devuelve ``(registro, was_created)``.

    Misma semantica de idempotencia que :func:`create_downtime_event`.
    """
    record = ProductionRecord(
        line_id=line_id,
        interval_start=interval_start,
        interval_end=interval_end,
        total_count=total_count,
        good_count=good_count,
        ideal_cycle_time_seconds=ideal_cycle_time_seconds,
        source=source,
        external_id=external_id,
    )
    if source is None or external_id is None:
        session.add(record)
        session.flush()
        return record, True

    try:
        with session.begin_nested():
            session.add(record)
            session.flush()
    except IntegrityError as exc:
        if not _is_unique_violation(
            exc,
            constraint_name="uq_production_record_source",
            column_names=("source", "external_id"),
        ):
            raise
        existing = session.execute(
            select(ProductionRecord).where(
                ProductionRecord.source == source, ProductionRecord.external_id == external_id
            )
        ).scalar_one()
        differences = _differing_fields(
            {
                "line_id": (existing.line_id, line_id),
                "interval_start": (existing.interval_start, interval_start),
                "interval_end": (existing.interval_end, interval_end),
                "total_count": (existing.total_count, total_count),
                "good_count": (existing.good_count, good_count),
                "ideal_cycle_time_seconds": (
                    existing.ideal_cycle_time_seconds,
                    ideal_cycle_time_seconds,
                ),
            }
        )
        if differences:
            raise DuplicateWithDifferentPayloadError(
                entity="production_record",
                source=source,
                external_id=external_id,
                differing_fields=differences,
            ) from exc
        return existing, False
    return record, True
