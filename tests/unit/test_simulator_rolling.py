"""Deterministic rolling-feed planning without network calls."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from scripts.simulator.config import LIVE_SOURCE
from scripts.simulator.generator import generate
from scripts.simulator.model import LineConfig, MachineConfig, SimulatorConfig
from scripts.simulator.rolling import (
    CATCH_UP_HOURS,
    build_rolling_plan,
    daily_seed,
    latest_closed_bucket,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from paro.db.base import Base
from paro.db.models import DowntimeEvent, DowntimeReason, Machine, ProductionLine, ProductionRecord


def _database() -> tuple[Session, SimulatorConfig]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    line = ProductionLine(code="SIM-L1", name="SIM-L1", timezone="America/Monterrey")
    session.add(line)
    session.flush()
    machine = Machine(line_id=line.id, code="M1", name="SIM-L1 M1")
    reasons = {
        code: DowntimeReason(code=code, name=code, default_is_planned=code == "CHG-P")
        for code in ("CHG-P", "FLA-M", "FLA-E", "FLA-N", "FLA-S", "ATC-M", "DES-M", "AJT-M")
    }
    session.add_all([machine, *reasons.values()])
    session.commit()
    config = SimulatorConfig(
        lines=(LineConfig(line.id, Decimal("30.000")),),
        machines=(MachineConfig(machine.id, line.id),),
        reason_ids={code: reason.id for code, reason in reasons.items()},
    )
    return session, config


def test_latest_closed_bucket_floors_to_quarter_hour() -> None:
    now = datetime(2026, 8, 20, 12, 29, 59, tzinfo=UTC)
    assert latest_closed_bucket(now) == datetime(2026, 8, 20, 12, 15, tzinfo=UTC)


def test_daily_seed_is_repeatable_and_changes_by_day() -> None:
    first = datetime(2026, 8, 20, tzinfo=UTC).date()
    second = first + timedelta(days=1)
    assert daily_seed(42, first) == daily_seed(42, first)
    assert daily_seed(42, first) != daily_seed(42, second)


def test_adjacent_generator_windows_have_no_external_id_collisions() -> None:
    session, config = _database()
    try:
        start = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
        first = generate(config, 42, start, start + timedelta(minutes=15))
        second = generate(config, 42, start + timedelta(minutes=15), start + timedelta(minutes=30))
        first_ids = {item.external_id for item in first.production_records} | {
            item.external_id for item in first.downtime_events
        }
        second_ids = {item.external_id for item in second.production_records} | {
            item.external_id for item in second.downtime_events
        }
        assert first_ids.isdisjoint(second_ids)
    finally:
        session.close()


def test_empty_database_bootstraps_only_live_source_within_48_hours() -> None:
    session, config = _database()
    try:
        now = datetime(2026, 8, 20, 18, 7, tzinfo=UTC)
        plan = build_rolling_plan(session, config, now=now)
        assert plan.cutoff == datetime(2026, 8, 20, 18, 0, tzinfo=UTC)
        assert plan.horizon_start == plan.cutoff - timedelta(hours=CATCH_UP_HOURS)
        assert plan.run.production_records
        assert all(item.source == LIVE_SOURCE for item in plan.run.production_records)
        assert all(
            item.interval_start >= plan.horizon_start for item in plan.run.production_records
        )
        assert all(item.interval_end <= plan.cutoff for item in plan.run.production_records)
        assert plan.gap_detected is False
    finally:
        session.close()


def test_open_event_is_closed_on_a_later_plan() -> None:
    session, config = _database()
    try:
        early = build_rolling_plan(session, config, now=datetime(2026, 8, 20, 12, 16, tzinfo=UTC))
        open_draft = next(event for event in early.run.downtime_events if event.ended_at is None)
        persisted = DowntimeEvent(
            line_id=open_draft.line_id,
            machine_id=open_draft.machine_id,
            started_at=open_draft.started_at,
            ended_at=None,
            reason_id=open_draft.reason_id,
            is_planned=open_draft.is_planned,
            source=open_draft.source,
            external_id=open_draft.external_id,
        )
        session.add(persisted)
        session.commit()

        later = build_rolling_plan(session, config, now=datetime(2026, 8, 20, 13, 1, tzinfo=UTC))
        closing = next(item for item in later.closings if item.event_id == persisted.id)
        assert closing.ended_at > persisted.started_at
    finally:
        session.close()


def test_old_live_row_marks_gap_beyond_catch_up_horizon() -> None:
    session, config = _database()
    try:
        now = datetime(2026, 8, 20, 18, 7, tzinfo=UTC)
        old_start = now - timedelta(hours=CATCH_UP_HOURS + 2)
        line_id = config.lines[0].line_id
        session.add(
            ProductionRecord(
                line_id=line_id,
                interval_start=old_start,
                interval_end=old_start + timedelta(minutes=15),
                total_count=1,
                good_count=1,
                ideal_cycle_time_seconds=Decimal("30.000"),
                source=LIVE_SOURCE,
                external_id="old-live-row",
            )
        )
        session.commit()
        assert build_rolling_plan(session, config, now=now).gap_detected is True
    finally:
        session.close()
