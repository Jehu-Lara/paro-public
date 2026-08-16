"""Repositories with real idempotency by ``(source, external_id)``.

Follows Stripe's "idempotent requests" pattern: the same key with the
same payload returns the existing row without an exception; the same key
with a different payload raises
:class:`DuplicateWithDifferentPayloadError` instead of duplicating the
row or silently letting the conflict through.

The payload comparison covers **every** business field of the model (not
just a subset): comparing only some of them would let a real change in an
uncompared field be treated as if it were the same data.

No OEE logic here: these repositories only persist rows.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from paro.db.exceptions import DuplicateWithDifferentPayloadError, StaleUpdateError
from paro.db.models import AuditLog, DowntimeEvent, ProductionRecord
from paro.json_safe import json_safe

__all__ = ["create_downtime_event", "create_production_record", "update_downtime_event"]


def _is_unique_violation(
    exc: IntegrityError, *, constraint_name: str, column_names: tuple[str, ...], table_name: str
) -> bool:
    """``True`` if ``exc`` is the UNIQUE violation for ``constraint_name``.

    Keeps a generic ``except IntegrityError`` from swallowing a different
    integrity violation (a CHECK or an FK) and mistaking it for a duplicate
    idempotency key. The error text is driver-specific -- psycopg
    (PostgreSQL) and sqlite3 don't share a format, see the examples below --
    so both are recognized instead of assuming one.

    PostgreSQL/psycopg: anchored to ``constraint_name``, which is stable
    across dialects via ``paro.db.base.NAMING_CONVENTION`` -- unambiguous by
    itself, no ``table_name`` needed: ``...unique constraint
    "uq_downtime_event_source"``.

    SQLite: the driver never includes the constraint name in a UNIQUE
    violation (verified empirically -- unlike its CHECK violations, which do
    name the constraint), only ``table.column``: ``UNIQUE constraint
    failed: downtime_event.source, downtime_event.external_id``. Without
    also requiring ``table_name``, ``downtime_event`` and
    ``production_record`` share the same ``column_names`` ("source",
    "external_id"), so a violation on one table could be misattributed to
    the other.
    """
    message = str(exc.orig)
    if f'"{constraint_name}"' in message:
        return True
    return "UNIQUE constraint failed" in message and all(
        f"{table_name}.{name}" in message for name in column_names
    )


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
    """Inserts a downtime event; returns ``(event, was_created)``.

    Without ``source`` and ``external_id`` there's no possible idempotency
    key: the row is inserted directly and ``was_created`` is always
    ``True``. With both present, a UNIQUE clash is resolved by comparing
    the full business payload against the existing row.
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
            exc,
            constraint_name="uq_downtime_event_source",
            column_names=("source", "external_id"),
            table_name="downtime_event",
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
    """Inserts a production record; returns ``(record, was_created)``.

    Same idempotency semantics as :func:`create_downtime_event`.
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
            table_name="production_record",
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


def update_downtime_event(
    session: Session,
    *,
    event: DowntimeEvent,
    expected_updated_at: datetime,
    changes: dict[str, Any],
    actor: str | None,
) -> tuple[DowntimeEvent, bool]:
    """Applies a partial correction to ``event``; returns ``(event, was_changed)``.

    ``expected_updated_at`` must match ``event.updated_at`` or this raises
    :class:`StaleUpdateError` -- optimistic concurrency, no row lock held
    between the caller reading the row and submitting this call.

    ``changes`` holds only the fields the caller actually sent (see
    ``DowntimeEventPatch.model_fields_set`` at the call site); a value equal
    to the current one is filtered out here too, so resubmitting identical
    values is a no-op, same idempotent philosophy as
    :func:`create_downtime_event`. A no-op writes no ``audit_log`` row and
    leaves ``updated_at`` untouched.
    """
    if event.updated_at != expected_updated_at:
        raise StaleUpdateError(
            entity="downtime_event",
            id=event.id,
            expected_updated_at=expected_updated_at,
            actual_updated_at=event.updated_at,
        )

    diff: dict[str, list[Any]] = {}
    for field, new_value in changes.items():
        old_value = getattr(event, field)
        if old_value != new_value:
            diff[field] = [old_value, new_value]
            setattr(event, field, new_value)

    if not diff:
        return event, False

    session.flush()
    session.add(
        AuditLog(
            downtime_event_id=event.id,
            changed_fields=json_safe(diff),
            actor=actor,
        )
    )
    session.flush()
    return event, True
