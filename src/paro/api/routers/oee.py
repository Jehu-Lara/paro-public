"""Router for ``GET /oee``.

Pure adapter: builds ``Interval``/``DowntimeSpan`` from the
``downtime_event``/``production_record`` rows in the requested window and
calls ``paro.domain.oee.calculate_oee`` exactly once. The OEE formula is
not reimplemented here.

``shift.planned_break_minutes`` does NOT participate in this calculation:
it's an integer number of minutes with no associated ``start``/``end``,
and there's no way to turn it into a ``DowntimeSpan`` without inventing
when the break happens within the shift. The actual planned-time
mechanism ``calculate_oee`` consumes is ``downtime_event.is_planned``
(see ``scripts/seed_demo.py``, which already follows this pattern), so
the window the client requests (``start``/``end``) is literally the
domain's ``window``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from paro.api.deps import get_db
from paro.api.schemas.oee import OEEResponse
from paro.db.models import DowntimeEvent, ProductionLine, ProductionRecord
from paro.domain.intervals import Interval, require_aware
from paro.domain.oee import DowntimeSpan, calculate_oee
from paro.domain.warnings import Warning

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["oee"])


def _require_aware(value: datetime, field: str) -> None:
    """Delegates to domain.intervals.require_aware; ValueError becomes 422.

    Keeps the router rejecting exactly what the domain would reject later
    when it builds ``Interval`` -- no separate, weaker tz-aware check here.
    """
    try:
        require_aware(value, field)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _ideal_time_total_seconds(records: list[ProductionRecord]) -> Decimal:
    """Exact sum of ``ideal_cycle_time_seconds * total_count`` per record.

    This is the aggregate ideal time that ``Performance`` uses (see
    ``domain/oee.py``). Never averaged or divided by ``total_count``:
    dividing to average and letting the domain multiply back loses
    precision in the general case (the quotient may have no finite decimal
    representation). ``Decimal("0")`` when there are no records, no special
    case needed: ``sum`` over an empty list already returns the start
    value.
    """
    return sum(
        (record.ideal_cycle_time_seconds * record.total_count for record in records), Decimal("0")
    )


@router.get("/oee", response_model=OEEResponse)
def get_oee(
    line_id: int = Query(...),
    start: datetime = Query(...),  # noqa: B008
    end: datetime = Query(...),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> OEEResponse:
    """Calculates OEE for ``line_id`` in the ``[start, end)`` window.

    404 if ``line_id`` doesn't exist. If it exists but there are no events
    in the window, 200 with ``None`` components and the warnings
    ``calculate_oee`` already emits for zero denominators.
    """
    _require_aware(start, "start")
    _require_aware(end, "end")
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be greater than start.")

    if db.get(ProductionLine, line_id) is None:
        raise HTTPException(status_code=404, detail=f"production line {line_id} not found")

    downtime_events = db.scalars(
        select(DowntimeEvent).where(
            DowntimeEvent.line_id == line_id,
            DowntimeEvent.started_at < end,
            (DowntimeEvent.ended_at.is_(None)) | (DowntimeEvent.ended_at > start),
        )
    ).all()
    planned_downtimes = [
        DowntimeSpan(start=event.started_at, end=event.ended_at)
        for event in downtime_events
        if event.is_planned
    ]
    unplanned_downtimes = [
        DowntimeSpan(start=event.started_at, end=event.ended_at)
        for event in downtime_events
        if not event.is_planned
    ]

    production_records_overlapping = list(
        db.scalars(
            select(ProductionRecord).where(
                ProductionRecord.line_id == line_id,
                ProductionRecord.interval_start < end,
                ProductionRecord.interval_end > start,
            )
        ).all()
    )
    production_records = [
        record
        for record in production_records_overlapping
        if record.interval_start >= start and record.interval_end <= end
    ]
    total_count = sum(record.total_count for record in production_records)
    good_count = sum(record.good_count for record in production_records)
    ideal_time_total_seconds = _ideal_time_total_seconds(production_records)

    result = calculate_oee(
        window=Interval(start, end),
        planned_downtimes=planned_downtimes,
        unplanned_downtimes=unplanned_downtimes,
        total_count=total_count,
        good_count=good_count,
        ideal_time_total_seconds=ideal_time_total_seconds,
    )

    warnings = list(result.warnings)
    if len(production_records) < len(production_records_overlapping):
        warnings.append(Warning.PARTIAL_PRODUCTION_EXCLUDED)

    return OEEResponse(
        line_id=line_id,
        window_start=start,
        window_end=end,
        availability=result.availability,
        performance_raw=result.performance_raw,
        performance_capped=result.performance_capped,
        quality=result.quality,
        oee=result.oee,
        planned_production_time_seconds=result.planned_production_time_seconds,
        run_time_seconds=result.run_time_seconds,
        warnings=warnings,
    )
