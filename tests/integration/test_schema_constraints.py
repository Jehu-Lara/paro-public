"""Constraints del esquema: UNIQUE, CHECK, FK, y round-trips de tipos.

Cada prueba usa su propio archivo SQLite temporal (fixture ``migrated_engine``
en ``conftest.py``), migrado con Alembic igual que en produccion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from paro.db.models import DowntimeEvent, DowntimeReason, ProductionLine, ProductionRecord


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


def test_duplicate_source_external_id_rejected_for_downtime_event(migrated_engine: Engine) -> None:
    now = datetime.now(UTC)
    with Session(migrated_engine) as session:
        line = _make_line(session)
        reason = _make_reason(session)
        session.add(
            DowntimeEvent(
                line_id=line.id,
                started_at=now,
                ended_at=now + timedelta(minutes=5),
                reason_id=reason.id,
                is_planned=False,
                source="mes",
                external_id="evt-1",
            )
        )
        session.commit()

        session.add(
            DowntimeEvent(
                line_id=line.id,
                started_at=now + timedelta(hours=1),
                ended_at=now + timedelta(hours=1, minutes=5),
                reason_id=reason.id,
                is_planned=False,
                source="mes",
                external_id="evt-1",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_duplicate_source_external_id_rejected_for_production_record(
    migrated_engine: Engine,
) -> None:
    now = datetime.now(UTC)
    with Session(migrated_engine) as session:
        line = _make_line(session)
        session.add(
            ProductionRecord(
                line_id=line.id,
                interval_start=now,
                interval_end=now + timedelta(hours=1),
                total_count=100,
                good_count=95,
                ideal_cycle_time_seconds=Decimal("12.5"),
                source="mes",
                external_id="rec-1",
            )
        )
        session.commit()

        session.add(
            ProductionRecord(
                line_id=line.id,
                interval_start=now + timedelta(hours=1),
                interval_end=now + timedelta(hours=2),
                total_count=100,
                good_count=95,
                ideal_cycle_time_seconds=Decimal("12.5"),
                source="mes",
                external_id="rec-1",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_invalid_interval_rejected(migrated_engine: Engine) -> None:
    now = datetime.now(UTC)
    with Session(migrated_engine) as session:
        line = _make_line(session)
        session.add(
            ProductionRecord(
                line_id=line.id,
                interval_start=now,
                interval_end=now - timedelta(minutes=1),
                total_count=10,
                good_count=5,
                ideal_cycle_time_seconds=Decimal("1.0"),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(("total_count", "good_count"), [(10, 11), (10, -1)])
def test_invalid_counts_rejected(
    migrated_engine: Engine, total_count: int, good_count: int
) -> None:
    now = datetime.now(UTC)
    with Session(migrated_engine) as session:
        line = _make_line(session)
        session.add(
            ProductionRecord(
                line_id=line.id,
                interval_start=now,
                interval_end=now + timedelta(hours=1),
                total_count=total_count,
                good_count=good_count,
                ideal_cycle_time_seconds=Decimal("1.0"),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_negative_ideal_cycle_time_rejected(migrated_engine: Engine) -> None:
    now = datetime.now(UTC)
    with Session(migrated_engine) as session:
        line = _make_line(session)
        session.add(
            ProductionRecord(
                line_id=line.id,
                interval_start=now,
                interval_end=now + timedelta(hours=1),
                total_count=10,
                good_count=5,
                ideal_cycle_time_seconds=Decimal("-1"),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_invalid_foreign_key_rejected(migrated_engine: Engine) -> None:
    """Prueba directa de que ``PRAGMA foreign_keys=ON`` esta activo.

    Sin el PRAGMA, SQLite acepta silenciosamente un ``machine_id`` que no
    existe: este test falla exactamente en ese escenario.
    """
    now = datetime.now(UTC)
    with Session(migrated_engine) as session:
        line = _make_line(session)
        reason = _make_reason(session)
        session.add(
            DowntimeEvent(
                line_id=line.id,
                machine_id=999_999,
                started_at=now,
                ended_at=now + timedelta(minutes=5),
                reason_id=reason.id,
                is_planned=False,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_utc_aware_datetime_round_trip_preserves_instant(migrated_engine: Engine) -> None:
    local = datetime(2026, 8, 12, 6, 0, 0, tzinfo=ZoneInfo("America/Monterrey"))
    with Session(migrated_engine) as session:
        line = _make_line(session)
        record = ProductionRecord(
            line_id=line.id,
            interval_start=local,
            interval_end=local + timedelta(hours=1),
            total_count=10,
            good_count=10,
            ideal_cycle_time_seconds=Decimal("1.0"),
        )
        session.add(record)
        session.commit()
        record_id = record.id

    with Session(migrated_engine) as session:
        fetched = session.get(ProductionRecord, record_id)
        assert fetched is not None
        assert fetched.interval_start.tzinfo is not None
        assert fetched.interval_start == local.astimezone(UTC)


def test_decimal_round_trip_preserves_precision(migrated_engine: Engine) -> None:
    value = Decimal("12.345")
    now = datetime.now(UTC)
    with Session(migrated_engine) as session:
        line = _make_line(session)
        record = ProductionRecord(
            line_id=line.id,
            interval_start=now,
            interval_end=now + timedelta(hours=1),
            total_count=10,
            good_count=10,
            ideal_cycle_time_seconds=value,
        )
        session.add(record)
        session.commit()
        record_id = record.id

    with Session(migrated_engine) as session:
        fetched = session.get(ProductionRecord, record_id)
        assert fetched is not None
        assert isinstance(fetched.ideal_cycle_time_seconds, Decimal)
        assert fetched.ideal_cycle_time_seconds == value
