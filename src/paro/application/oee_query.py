"""Read-side orchestration for OEE.

This module is the single bridge between persisted manufacturing facts and
``paro.domain.oee.calculate_oee``.  HTTP adapters may choose windows and map
responses, but they must not rebuild the OEE formula.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from paro.db.models import DowntimeEvent, ProductionLine, ProductionRecord
from paro.domain.intervals import Interval
from paro.domain.oee import DowntimeSpan, OeeResult, calculate_oee
from paro.domain.warnings import Warning

__all__ = ["LineNotFoundError", "OeeQueryResult", "query_line_oee"]


class LineNotFoundError(LookupError):
    """Raised when an OEE query references an unknown production line."""


@dataclass(frozen=True, slots=True)
class OeeQueryResult:
    """Domain result plus the persisted facts used to produce it."""

    line: ProductionLine
    window: Interval
    result: OeeResult
    warnings: tuple[Warning, ...]
    production_records: tuple[ProductionRecord, ...]
    downtime_events: tuple[DowntimeEvent, ...]
    total_count: int
    good_count: int


def _ideal_time_total_seconds(records: list[ProductionRecord]) -> Decimal:
    return sum(
        (record.ideal_cycle_time_seconds * record.total_count for record in records),
        Decimal("0"),
    )


def query_line_oee(
    session: Session, *, line_id: int, start: datetime, end: datetime
) -> OeeQueryResult:
    """Loads one window and invokes the pure OEE engine exactly once."""
    window = Interval(start, end)
    line = session.get(ProductionLine, line_id)
    if line is None:
        raise LineNotFoundError(f"production line {line_id} not found")

    downtime_events = list(
        session.scalars(
            select(DowntimeEvent).where(
                DowntimeEvent.line_id == line_id,
                DowntimeEvent.started_at < window.end,
                (DowntimeEvent.ended_at.is_(None)) | (DowntimeEvent.ended_at > window.start),
            )
        ).all()
    )
    planned = [
        DowntimeSpan(start=event.started_at, end=event.ended_at)
        for event in downtime_events
        if event.is_planned
    ]
    unplanned = [
        DowntimeSpan(start=event.started_at, end=event.ended_at)
        for event in downtime_events
        if not event.is_planned
    ]

    overlapping = list(
        session.scalars(
            select(ProductionRecord).where(
                ProductionRecord.line_id == line_id,
                ProductionRecord.interval_start < window.end,
                ProductionRecord.interval_end > window.start,
            )
        ).all()
    )
    included = [
        record
        for record in overlapping
        if record.interval_start >= window.start and record.interval_end <= window.end
    ]
    total_count = sum(record.total_count for record in included)
    good_count = sum(record.good_count for record in included)

    result = calculate_oee(
        window=window,
        planned_downtimes=planned,
        unplanned_downtimes=unplanned,
        total_count=total_count,
        good_count=good_count,
        ideal_time_total_seconds=_ideal_time_total_seconds(included),
    )
    warnings = list(result.warnings)
    if len(included) < len(overlapping):
        warnings.append(Warning.PARTIAL_PRODUCTION_EXCLUDED)

    return OeeQueryResult(
        line=line,
        window=window,
        result=result,
        warnings=tuple(warnings),
        production_records=tuple(included),
        downtime_events=tuple(downtime_events),
        total_count=total_count,
        good_count=good_count,
    )
