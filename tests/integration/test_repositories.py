"""Idempotencia real de los repositorios: mismo payload no duplica, payload
distinto con la misma clave (``source``, ``external_id``) lanza un error de
dominio y no deja fila basura.

Cada prueba usa su propio archivo SQLite temporal (fixture ``migrated_engine``
en ``conftest.py``), migrado con Alembic igual que en produccion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from paro.db.exceptions import DuplicateWithDifferentPayloadError
from paro.db.models import DowntimeEvent, DowntimeReason, ProductionLine, ProductionRecord
from paro.db.repositories import (
    _is_unique_violation,
    create_downtime_event,
    create_production_record,
)

NOW = datetime(2026, 8, 10, 22, 0, tzinfo=UTC)


def _make_line(session: Session, code: str = "L1") -> ProductionLine:
    line = ProductionLine(code=code, name="Linea 1", timezone="America/Monterrey", active=True)
    session.add(line)
    session.flush()
    return line


def _make_reason(session: Session, code: str = "R1") -> DowntimeReason:
    reason = DowntimeReason(code=code, name="Falla mecanica", default_is_planned=False)
    session.add(reason)
    session.flush()
    return reason


def _count(session: Session, model: type[DowntimeEvent] | type[ProductionRecord]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_create_downtime_event_new_is_created(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        line = _make_line(session)
        reason = _make_reason(session)

        event, was_created = create_downtime_event(
            session,
            line_id=line.id,
            reason_id=reason.id,
            started_at=NOW,
            ended_at=NOW + timedelta(minutes=5),
            is_planned=False,
            source="mes",
            external_id="evt-1",
        )
        session.commit()

        assert was_created is True
        assert event.id is not None
        assert _count(session, DowntimeEvent) == 1


def test_create_downtime_event_same_payload_is_noop(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        line = _make_line(session)
        reason = _make_reason(session)
        first, first_created = create_downtime_event(
            session,
            line_id=line.id,
            reason_id=reason.id,
            started_at=NOW,
            ended_at=NOW + timedelta(minutes=5),
            is_planned=False,
            source="mes",
            external_id="evt-1",
        )
        session.commit()
        second, second_created = create_downtime_event(
            session,
            line_id=line.id,
            reason_id=reason.id,
            started_at=NOW,
            ended_at=NOW + timedelta(minutes=5),
            is_planned=False,
            source="mes",
            external_id="evt-1",
        )
        session.commit()

        assert first_created is True
        assert second_created is False
        assert second.id == first.id
        assert _count(session, DowntimeEvent) == 1


def test_create_downtime_event_different_payload_raises(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        line = _make_line(session)
        reason = _make_reason(session)
        create_downtime_event(
            session,
            line_id=line.id,
            reason_id=reason.id,
            started_at=NOW,
            ended_at=NOW + timedelta(minutes=5),
            is_planned=False,
            source="mes",
            external_id="evt-1",
        )
        session.commit()

        with pytest.raises(DuplicateWithDifferentPayloadError) as exc_info:
            create_downtime_event(
                session,
                line_id=line.id,
                reason_id=reason.id,
                started_at=NOW,
                ended_at=NOW + timedelta(minutes=45),  # distinto: 45 min, no 5
                is_planned=False,
                source="mes",
                external_id="evt-1",
            )

        assert "ended_at" in exc_info.value.differing_fields
        assert _count(session, DowntimeEvent) == 1
        # La sesion sigue utilizable tras el conflicto (savepoint, no la
        # transaccion completa, fue lo que se deshizo).
        session.commit()


def test_create_production_record_new_is_created(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        line = _make_line(session)

        record, was_created = create_production_record(
            session,
            line_id=line.id,
            interval_start=NOW,
            interval_end=NOW + timedelta(hours=1),
            total_count=100,
            good_count=95,
            ideal_cycle_time_seconds=Decimal("12.5"),
            source="mes",
            external_id="rec-1",
        )
        session.commit()

        assert was_created is True
        assert record.id is not None
        assert _count(session, ProductionRecord) == 1


def test_create_production_record_same_payload_is_noop(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        line = _make_line(session)
        first, first_created = create_production_record(
            session,
            line_id=line.id,
            interval_start=NOW,
            interval_end=NOW + timedelta(hours=1),
            total_count=100,
            good_count=95,
            ideal_cycle_time_seconds=Decimal("12.5"),
            source="mes",
            external_id="rec-1",
        )
        session.commit()
        second, second_created = create_production_record(
            session,
            line_id=line.id,
            interval_start=NOW,
            interval_end=NOW + timedelta(hours=1),
            total_count=100,
            good_count=95,
            ideal_cycle_time_seconds=Decimal("12.5"),
            source="mes",
            external_id="rec-1",
        )
        session.commit()

        assert first_created is True
        assert second_created is False
        assert second.id == first.id
        assert _count(session, ProductionRecord) == 1


def test_create_production_record_different_payload_raises(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        line = _make_line(session)
        create_production_record(
            session,
            line_id=line.id,
            interval_start=NOW,
            interval_end=NOW + timedelta(hours=1),
            total_count=100,
            good_count=95,
            ideal_cycle_time_seconds=Decimal("12.5"),
            source="mes",
            external_id="rec-1",
        )
        session.commit()

        with pytest.raises(DuplicateWithDifferentPayloadError) as exc_info:
            create_production_record(
                session,
                line_id=line.id,
                interval_start=NOW,
                interval_end=NOW + timedelta(hours=1),
                total_count=100,
                good_count=80,  # distinto: 80, no 95
                ideal_cycle_time_seconds=Decimal("12.5"),
                source="mes",
                external_id="rec-1",
            )

        assert "good_count" in exc_info.value.differing_fields
        assert _count(session, ProductionRecord) == 1
        session.commit()


def test_is_unique_violation_does_not_cross_attribute_between_tables(
    migrated_engine: Engine,
) -> None:
    """Reproduces the exact gap ``column_names`` alone allowed: a
    ``production_record`` UNIQUE violation must not be misidentified as a
    ``downtime_event`` one just because both tables share column names.
    """
    with Session(migrated_engine) as session:
        line = _make_line(session)
        session.add(
            ProductionRecord(
                line_id=line.id,
                interval_start=NOW,
                interval_end=NOW + timedelta(hours=1),
                total_count=10,
                good_count=10,
                ideal_cycle_time_seconds=Decimal("1.0"),
                source="mes",
                external_id="shared-key",
            )
        )
        session.commit()

        session.add(
            ProductionRecord(
                line_id=line.id,
                interval_start=NOW + timedelta(hours=2),
                interval_end=NOW + timedelta(hours=3),
                total_count=10,
                good_count=10,
                ideal_cycle_time_seconds=Decimal("1.0"),
                source="mes",
                external_id="shared-key",
            )
        )
        with pytest.raises(IntegrityError) as exc_info:
            session.commit()
        session.rollback()

        violation = exc_info.value

    assert _is_unique_violation(
        violation,
        constraint_name="uq_production_record_source",
        column_names=("source", "external_id"),
        table_name="production_record",
    )
    assert not _is_unique_violation(
        violation,
        constraint_name="uq_downtime_event_source",
        column_names=("source", "external_id"),
        table_name="downtime_event",
    )
