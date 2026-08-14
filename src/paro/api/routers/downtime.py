"""Router for ``downtime_event``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from paro.api.deps import get_db
from paro.api.schemas.downtime import DowntimeEventCreate, DowntimeEventResponse
from paro.db.models import DowntimeReason, Machine, ProductionLine
from paro.db.repositories import create_downtime_event

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["downtime-events"])


@router.post("/downtime-events", response_model=DowntimeEventResponse)
def post_downtime_event(
    payload: DowntimeEventCreate,
    response: Response,
    db: Session = Depends(get_db),  # noqa: B008
) -> DowntimeEventResponse:
    """Records a downtime event.

    Idempotent by ``(source, external_id)``: same payload -> 200 without
    duplicating the row, different payload with the same key -> 409 (see
    ``paro.api.errors``).
    """
    if db.get(ProductionLine, payload.line_id) is None:
        detail = f"production line {payload.line_id} not found"
        raise HTTPException(status_code=404, detail=detail)
    if payload.machine_id is not None and db.get(Machine, payload.machine_id) is None:
        raise HTTPException(status_code=404, detail=f"machine {payload.machine_id} not found")
    if db.get(DowntimeReason, payload.reason_id) is None:
        detail = f"downtime reason {payload.reason_id} not found"
        raise HTTPException(status_code=404, detail=detail)

    event, was_created = create_downtime_event(
        db,
        line_id=payload.line_id,
        machine_id=payload.machine_id,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        reason_id=payload.reason_id,
        is_planned=payload.is_planned,
        operator_note=payload.operator_note,
        source=payload.source,
        external_id=payload.external_id,
    )
    db.commit()

    response.status_code = status.HTTP_201_CREATED if was_created else status.HTTP_200_OK
    return DowntimeEventResponse.model_validate(event)
