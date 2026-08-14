"""Router for ``production_record``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from paro.api.deps import get_db
from paro.api.schemas.production import ProductionRecordCreate, ProductionRecordResponse
from paro.db.models import ProductionLine
from paro.db.repositories import create_production_record

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["production-records"])


@router.post("/production-records", response_model=ProductionRecordResponse)
def post_production_record(
    payload: ProductionRecordCreate,
    response: Response,
    db: Session = Depends(get_db),  # noqa: B008
) -> ProductionRecordResponse:
    """Records a production count.

    Idempotent by ``(source, external_id)``: same payload -> 200 without
    duplicating the row, different payload with the same key -> 409 (see
    ``paro.api.errors``).
    """
    if db.get(ProductionLine, payload.line_id) is None:
        detail = f"production line {payload.line_id} not found"
        raise HTTPException(status_code=404, detail=detail)

    record, was_created = create_production_record(
        db,
        line_id=payload.line_id,
        interval_start=payload.interval_start,
        interval_end=payload.interval_end,
        total_count=payload.total_count,
        good_count=payload.good_count,
        ideal_cycle_time_seconds=payload.ideal_cycle_time_seconds,
        source=payload.source,
        external_id=payload.external_id,
    )
    db.commit()

    response.status_code = status.HTTP_201_CREATED if was_created else status.HTTP_200_OK
    return ProductionRecordResponse.model_validate(record)
