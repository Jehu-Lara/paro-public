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

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from paro.api.deps import get_db
from paro.api.schemas.oee import OEEResponse
from paro.application.oee_query import (
    LineNotFoundError,
    _ideal_time_total_seconds,
    query_line_oee,
)
from paro.domain.intervals import require_aware

__all__ = ["_ideal_time_total_seconds", "router"]

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

    try:
        snapshot = query_line_oee(db, line_id=line_id, start=start, end=end)
    except LineNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return OEEResponse(
        line_id=line_id,
        window_start=start,
        window_end=end,
        availability=snapshot.result.availability,
        performance_raw=snapshot.result.performance_raw,
        performance_capped=snapshot.result.performance_capped,
        quality=snapshot.result.quality,
        oee=snapshot.result.oee,
        planned_production_time_seconds=snapshot.result.planned_production_time_seconds,
        run_time_seconds=snapshot.result.run_time_seconds,
        warnings=list(snapshot.warnings),
    )
