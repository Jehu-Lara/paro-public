"""Views fact_downtime_event / fact_production_record (migration 002).

Corre contra el fixture ``migrated_engine`` (SQLite localmente y en el job
``quality`` de CI, PostgreSQL real en el job ``integration-postgres`` - ver
ADR 0003): las mismas aserciones valen para ambos dialectos, incluido el
calculo de duracion en segundos que la migracion resuelve con SQL distinto
por dialecto.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from paro.db.models import DowntimeEvent, DowntimeReason, Machine, ProductionLine, ProductionRecord


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


def test_views_exist(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)
    assert {"fact_downtime_event", "fact_production_record"} <= set(inspector.get_view_names())


def test_fact_downtime_event_duration_seconds(migrated_engine: Engine) -> None:
    now = datetime(2026, 8, 13, 10, 0, 0, tzinfo=UTC)
    with Session(migrated_engine) as session:
        line = _make_line(session)
        reason = _make_reason(session)
        machine = Machine(line_id=line.id, code="M1", name="Maquina 1")
        session.add(machine)
        session.flush()
        event = DowntimeEvent(
            line_id=line.id,
            machine_id=machine.id,
            started_at=now,
            ended_at=now + timedelta(minutes=5, seconds=30),
            reason_id=reason.id,
            is_planned=False,
        )
        session.add(event)
        session.commit()
        event_id = event.id

        row = (
            session.execute(
                text("SELECT * FROM fact_downtime_event WHERE downtime_event_id = :id"),
                {"id": event_id},
            )
            .mappings()
            .one()
        )

    assert row["line_code"] == "L1"
    assert row["machine_code"] == "M1"
    assert row["reason_code"] == "R1"
    assert not row["is_planned"]
    assert row["duration_seconds"] == 330


def test_fact_downtime_event_duration_seconds_null_when_open(migrated_engine: Engine) -> None:
    now = datetime(2026, 8, 13, 10, 0, 0, tzinfo=UTC)
    with Session(migrated_engine) as session:
        line = _make_line(session)
        reason = _make_reason(session)
        event = DowntimeEvent(
            line_id=line.id,
            started_at=now,
            ended_at=None,
            reason_id=reason.id,
            is_planned=False,
        )
        session.add(event)
        session.commit()
        event_id = event.id

        row = (
            session.execute(
                text("SELECT * FROM fact_downtime_event WHERE downtime_event_id = :id"),
                {"id": event_id},
            )
            .mappings()
            .one()
        )

    assert row["ended_at"] is None
    assert row["duration_seconds"] is None
    assert row["machine_id"] is None


def test_fact_production_record_rejected_count_and_duration(migrated_engine: Engine) -> None:
    now = datetime(2026, 8, 13, 6, 0, 0, tzinfo=UTC)
    with Session(migrated_engine) as session:
        line = _make_line(session)
        record = ProductionRecord(
            line_id=line.id,
            interval_start=now,
            interval_end=now + timedelta(hours=1),
            total_count=100,
            good_count=95,
            ideal_cycle_time_seconds=Decimal("12.5"),
        )
        session.add(record)
        session.commit()
        record_id = record.id

        row = (
            session.execute(
                text("SELECT * FROM fact_production_record WHERE production_record_id = :id"),
                {"id": record_id},
            )
            .mappings()
            .one()
        )

    assert row["rejected_count"] == 5
    assert row["interval_duration_seconds"] == 3600
    assert row["line_timezone"] == "America/Monterrey"
