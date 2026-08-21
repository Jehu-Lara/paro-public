"""Deterministic rolling plan for the public synthetic demo feed."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paro.db.models import DowntimeEvent, ProductionRecord
from scripts.simulator.config import (
    LIVE_ID_NAMESPACE,
    LIVE_SOURCE,
    MASTER_SEED,
    PRODUCTION_BUCKET_MINUTES,
    SHIFT_TIMEZONE,
)
from scripts.simulator.generator import generate
from scripts.simulator.model import DowntimeEventDraft, GeneratedRun, SimulatorConfig

__all__ = [
    "CATCH_UP_HOURS",
    "DowntimeClosing",
    "RollingPlan",
    "build_rolling_plan",
    "daily_seed",
    "latest_closed_bucket",
    "production_day_start",
]

CATCH_UP_HOURS = 48
_TZ = ZoneInfo(SHIFT_TIMEZONE)
_DAY_START = time(6)


@dataclass(frozen=True, slots=True)
class DowntimeClosing:
    event_id: int
    expected_updated_at: datetime
    ended_at: datetime


@dataclass(frozen=True, slots=True)
class RollingPlan:
    cutoff: datetime
    horizon_start: datetime
    run: GeneratedRun
    closings: tuple[DowntimeClosing, ...]
    gap_detected: bool


def latest_closed_bucket(now: datetime) -> datetime:
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError("now must be timezone-aware")
    utc = now.astimezone(UTC)
    minute = utc.minute - (utc.minute % PRODUCTION_BUCKET_MINUTES)
    return utc.replace(minute=minute, second=0, microsecond=0)


def production_day_start(moment: datetime) -> datetime:
    local = moment.astimezone(_TZ)
    business_date = local.date() if local.time() >= _DAY_START else local.date() - timedelta(days=1)
    return datetime.combine(business_date, _DAY_START, tzinfo=_TZ).astimezone(UTC)


def daily_seed(master_seed: int, business_date: date) -> int:
    digest = hashlib.sha256(f"{master_seed}:{business_date.isoformat()}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _daily_run(config: SimulatorConfig, start: datetime, master_seed: int) -> GeneratedRun:
    end = (start.astimezone(_TZ) + timedelta(days=1)).astimezone(UTC)
    run = generate(
        config,
        daily_seed(master_seed, start.astimezone(_TZ).date()),
        start,
        end,
        source=LIVE_SOURCE,
        id_namespace=LIVE_ID_NAMESPACE,
    )
    # A production-day boundary is an explicit simulator hand-off. Events
    # drawn past it close at the boundary so the next deterministic day never
    # produces counts during an event owned by the previous day.
    events = tuple(
        replace(event, ended_at=min(event.ended_at, end) if event.ended_at else None)
        for event in run.downtime_events
    )
    return GeneratedRun(production_records=run.production_records, downtime_events=events)


def _day_runs(
    config: SimulatorConfig,
    *,
    horizon_start: datetime,
    cutoff: datetime,
    master_seed: int,
) -> tuple[GeneratedRun, ...]:
    first_local_date = production_day_start(horizon_start).astimezone(_TZ).date()
    last_local_date = production_day_start(cutoff).astimezone(_TZ).date()
    runs = []
    day = first_local_date
    while day <= last_local_date:
        start = datetime.combine(day, _DAY_START, tzinfo=_TZ).astimezone(UTC)
        runs.append(_daily_run(config, start, master_seed))
        day += timedelta(days=1)
    return tuple(runs)


def _event_intersects_window(
    event: DowntimeEventDraft, *, horizon_start: datetime, cutoff: datetime
) -> bool:
    return event.started_at < cutoff and (event.ended_at is None or event.ended_at > horizon_start)


def build_rolling_plan(
    session: Session,
    config: SimulatorConfig,
    *,
    now: datetime,
    master_seed: int = MASTER_SEED,
) -> RollingPlan:
    """Returns only missing closed buckets/events plus open-event closures."""
    cutoff = latest_closed_bucket(now)
    horizon_start = cutoff - timedelta(hours=CATCH_UP_HOURS)
    runs = _day_runs(
        config,
        horizon_start=horizon_start,
        cutoff=cutoff,
        master_seed=master_seed,
    )
    production = tuple(
        record
        for run in runs
        for record in run.production_records
        if record.interval_start >= horizon_start and record.interval_end <= cutoff
    )
    deterministic_events = tuple(
        event
        for run in runs
        for event in run.downtime_events
        if _event_intersects_window(event, horizon_start=horizon_start, cutoff=cutoff)
    )

    production_ids = [record.external_id for record in production]
    existing_production_ids = (
        set(
            session.scalars(
                select(ProductionRecord.external_id).where(
                    ProductionRecord.source == LIVE_SOURCE,
                    ProductionRecord.external_id.in_(production_ids),
                )
            ).all()
        )
        if production_ids
        else set()
    )

    event_ids = [event.external_id for event in deterministic_events]
    existing_events = (
        {
            event.external_id: event
            for event in session.scalars(
                select(DowntimeEvent).where(
                    DowntimeEvent.source == LIVE_SOURCE,
                    DowntimeEvent.external_id.in_(event_ids),
                )
            ).all()
            if event.external_id is not None
        }
        if event_ids
        else {}
    )

    missing_production = tuple(
        record for record in production if record.external_id not in existing_production_ids
    )
    missing_events = []
    closings = []
    for event in deterministic_events:
        persisted = existing_events.get(event.external_id)
        deterministic_end = event.ended_at
        if persisted is None:
            visible_end = (
                deterministic_end if deterministic_end and deterministic_end <= cutoff else None
            )
            missing_events.append(replace(event, ended_at=visible_end))
        elif persisted.ended_at is None and deterministic_end and deterministic_end <= cutoff:
            closings.append(
                DowntimeClosing(
                    event_id=persisted.id,
                    expected_updated_at=persisted.updated_at,
                    ended_at=deterministic_end,
                )
            )

    latest_by_line: dict[int, datetime] = {
        line_id: latest
        for line_id, latest in session.execute(
            select(ProductionRecord.line_id, func.max(ProductionRecord.interval_end))
            .where(ProductionRecord.source == LIVE_SOURCE)
            .group_by(ProductionRecord.line_id)
        ).tuples()
        if latest is not None
    }
    gap_detected = bool(latest_by_line) and any(
        latest_by_line.get(line.line_id) is None or latest_by_line[line.line_id] < horizon_start
        for line in config.lines
    )
    return RollingPlan(
        cutoff=cutoff,
        horizon_start=horizon_start,
        run=GeneratedRun(
            production_records=missing_production,
            downtime_events=tuple(missing_events),
        ),
        closings=tuple(closings),
        gap_detected=gap_detected,
    )
