"""Router for ``downtime_event``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from paro.api.deps import get_db
from paro.api.rate_limit import is_trusted_ingest, limiter
from paro.api.schemas.downtime import DowntimeEventCreate, DowntimeEventPatch, DowntimeEventResponse
from paro.db.models import DowntimeEvent, DowntimeReason, Machine, ProductionLine
from paro.db.repositories import create_downtime_event, update_downtime_event

_PATCHABLE_FIELDS = (
    "machine_id",
    "started_at",
    "ended_at",
    "reason_id",
    "is_planned",
    "operator_note",
)

# Columns that are NOT NULL on DowntimeEvent: explicitly patching one of
# these to null would otherwise surface as an IntegrityError -> 500 instead
# of a clean 422. machine_id/ended_at/operator_note are genuinely nullable
# and excluded on purpose.
_NOT_NULLABLE_PATCH_FIELDS = ("started_at", "reason_id", "is_planned")

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["downtime-events"])


@router.post("/downtime-events", response_model=DowntimeEventResponse)
@limiter.limit("30/minute", exempt_when=is_trusted_ingest)
def post_downtime_event(
    request: Request,
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


@router.patch("/downtime-events/{id}", response_model=DowntimeEventResponse)
@limiter.limit("30/minute", exempt_when=is_trusted_ingest)
def patch_downtime_event(
    request: Request,
    id: int,
    payload: DowntimeEventPatch,
    db: Session = Depends(get_db),  # noqa: B008
) -> DowntimeEventResponse:
    """Applies a partial correction to a downtime event.

    Optimistic concurrency via ``payload.expected_updated_at`` -> 409 if it
    doesn't match the row's current ``updated_at`` (see ``paro.api.errors``).
    Only fields present in the request are considered; a value equal to the
    current one is a no-op (no new ``audit_log`` row, ``updated_at``
    unchanged).
    """
    event = db.get(DowntimeEvent, id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"downtime event {id} not found")

    fields_set = payload.model_fields_set
    for field in _NOT_NULLABLE_PATCH_FIELDS:
        if field in fields_set and getattr(payload, field) is None:
            raise HTTPException(status_code=422, detail=f"{field} cannot be null.")

    if (
        "machine_id" in fields_set
        and payload.machine_id is not None
        and db.get(Machine, payload.machine_id) is None
    ):
        raise HTTPException(status_code=404, detail=f"machine {payload.machine_id} not found")
    if (
        "reason_id" in fields_set
        and payload.reason_id is not None
        and db.get(DowntimeReason, payload.reason_id) is None
    ):
        detail = f"downtime reason {payload.reason_id} not found"
        raise HTTPException(status_code=404, detail=detail)

    started_at = payload.started_at
    if "started_at" in fields_set:
        if started_at is None:
            raise HTTPException(status_code=422, detail="started_at cannot be null.")
        merged_started_at = started_at
    else:
        merged_started_at = event.started_at
    merged_ended_at = payload.ended_at if "ended_at" in fields_set else event.ended_at
    if merged_ended_at is not None and merged_ended_at <= merged_started_at:
        raise HTTPException(status_code=422, detail="ended_at must be greater than started_at.")

    changes = {field: getattr(payload, field) for field in _PATCHABLE_FIELDS if field in fields_set}

    _, _ = update_downtime_event(
        db,
        event=event,
        expected_updated_at=payload.expected_updated_at,
        changes=changes,
        actor=payload.actor,
    )
    db.commit()

    return DowntimeEventResponse.model_validate(event)
