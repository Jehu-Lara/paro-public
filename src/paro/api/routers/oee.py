"""Router de ``GET /oee``.

Adaptador puro: arma ``Interval``/``DowntimeSpan`` a partir de las filas de
``downtime_event``/``production_record`` en la ventana pedida y llama a
``paro.domain.oee.calculate_oee`` una sola vez. La formula de OEE no se
reimplementa aqui.

``shift.planned_break_minutes`` NO participa en este calculo: es un entero de
minutos sin ``start``/``end`` asociado, y no hay forma de convertirlo en un
``DowntimeSpan`` sin inventar cuando ocurre el descanso dentro del turno. El
mecanismo real de tiempo planeado que ``calculate_oee`` consume es
``downtime_event.is_planned`` (ver ``scripts/seed_demo.py``, que ya sigue
este patron), asi que la ventana pedida por el cliente (``start``/``end``) es
literalmente el ``window`` del dominio.
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
from paro.domain.intervals import Interval
from paro.domain.oee import DowntimeSpan, calculate_oee

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["oee"])


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None:
        raise HTTPException(status_code=422, detail=f"{field} debe ser tz-aware.")


def _weighted_ideal_cycle_time(records: list[ProductionRecord]) -> Decimal:
    """Promedio de ``ideal_cycle_time_seconds`` ponderado por ``total_count``.

    Es lo unico que preserva ``ideal_cycle_time_seconds * total_count`` como
    el tiempo ideal total agregado, que es lo que ``Performance`` realmente
    usa (ver plan de la tarea). ``Decimal("0")`` si no hay conteo: en ese
    caso el dominio ya emite ``ZERO_TOTAL_COUNT``/``ZERO_RUN_TIME`` y el
    valor no afecta el resultado.
    """
    total = sum(record.total_count for record in records)
    if total == 0:
        return Decimal("0")
    weighted_sum = sum(
        (record.ideal_cycle_time_seconds * record.total_count for record in records), Decimal("0")
    )
    return weighted_sum / total


@router.get("/oee", response_model=OEEResponse)
def get_oee(
    line_id: int = Query(...),
    start: datetime = Query(...),  # noqa: B008
    end: datetime = Query(...),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> OEEResponse:
    """Calcula OEE para ``line_id`` en la ventana ``[start, end)``.

    404 si ``line_id`` no existe. Si existe pero no hay eventos en la
    ventana, 200 con los componentes ``None`` y los warnings que
    ``calculate_oee`` ya emite para denominadores en cero.
    """
    _require_aware(start, "start")
    _require_aware(end, "end")
    if end <= start:
        raise HTTPException(status_code=422, detail="end debe ser mayor que start.")

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

    production_records = list(
        db.scalars(
            select(ProductionRecord).where(
                ProductionRecord.line_id == line_id,
                ProductionRecord.interval_start >= start,
                ProductionRecord.interval_end <= end,
            )
        ).all()
    )
    total_count = sum(record.total_count for record in production_records)
    good_count = sum(record.good_count for record in production_records)
    ideal_cycle_time_seconds = _weighted_ideal_cycle_time(production_records)

    result = calculate_oee(
        window=Interval(start, end),
        planned_downtimes=planned_downtimes,
        unplanned_downtimes=unplanned_downtimes,
        total_count=total_count,
        good_count=good_count,
        ideal_cycle_time_seconds=ideal_cycle_time_seconds,
    )

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
        warnings=list(result.warnings),
    )
