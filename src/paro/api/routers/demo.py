"""Read-only portfolio demo endpoints.

The overview delegates OEE to the application service.  This router only
chooses a completed shift window and prepares supporting display facts.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from paro.api.deps import get_db
from paro.api.schemas.demo import (
    DemoLine,
    DemoOverviewResponse,
    DemoWindow,
    DowntimeReasonSummary,
)
from paro.application.oee_query import LineNotFoundError, query_line_oee
from paro.config import get_settings
from paro.db.models import DowntimeReason, ProductionLine, ProductionRecord
from paro.domain.intervals import Interval, clip

__all__ = ["router"]

router = APIRouter(tags=["demo"])

ShiftCode = Literal["A", "B", "C"]

_SHIFT_BOUNDARIES: tuple[tuple[ShiftCode, time], ...] = (
    ("A", time(6)),
    ("B", time(14)),
    ("C", time(22)),
)
_WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


def _completed_shift_window(
    data_through: datetime, timezone_name: str
) -> tuple[ShiftCode, Interval]:
    timezone = ZoneInfo(timezone_name)
    effective = (data_through - timedelta(microseconds=1)).astimezone(timezone)
    candidates: list[tuple[datetime, ShiftCode]] = []
    for day_offset in (-1, 0):
        day = effective.date() + timedelta(days=day_offset)
        for code, boundary in _SHIFT_BOUNDARIES:
            candidates.append((datetime.combine(day, boundary, tzinfo=timezone), code))
    shift_start, shift_code = max(item for item in candidates if item[0] <= effective)
    window_start = shift_start.astimezone(UTC)
    return shift_code, Interval(window_start, data_through)


def _demo_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail={"error": "demo_unavailable"})


@router.get("/demo", include_in_schema=False)
def demo_page() -> FileResponse:
    return FileResponse(_WEB_ROOT / "demo.html", media_type="text/html")


@router.get("/demo-assets/demo.css", include_in_schema=False)
def demo_css() -> FileResponse:
    return FileResponse(_WEB_ROOT / "demo.css", media_type="text/css")


@router.get("/demo-assets/demo.js", include_in_schema=False)
def demo_js() -> FileResponse:
    return FileResponse(_WEB_ROOT / "demo.js", media_type="text/javascript")


@router.get("/api/v1/demo/overview", response_model=DemoOverviewResponse)
def demo_overview(db: Session = Depends(get_db)) -> DemoOverviewResponse:  # noqa: B008
    settings = get_settings()
    generated_at = datetime.now(UTC)
    try:
        line = db.scalar(
            select(ProductionLine).where(ProductionLine.code == settings.demo_line_code)
        )
        if line is None:
            raise _demo_unavailable()
        data_through = db.scalar(
            select(func.max(ProductionRecord.interval_end)).where(
                ProductionRecord.line_id == line.id,
                ProductionRecord.source == settings.demo_source,
            )
        )
        if data_through is None:
            raise _demo_unavailable()

        shift_code, window = _completed_shift_window(data_through, line.timezone)
        snapshot = query_line_oee(db, line_id=line.id, start=window.start, end=window.end)
        reason_ids = {event.reason_id for event in snapshot.downtime_events}
        reason_rows = (
            db.execute(
                select(DowntimeReason.id, DowntimeReason.name).where(
                    DowntimeReason.id.in_(reason_ids)
                )
            ).all()
            if reason_ids
            else []
        )
        reason_names: dict[int, str] = {
            reason_id: reason_name for reason_id, reason_name in reason_rows
        }
    except HTTPException:
        raise
    except (LineNotFoundError, SQLAlchemyError, ValueError) as exc:
        raise _demo_unavailable() from exc

    seconds_by_reason: dict[str, int] = defaultdict(int)
    for event in snapshot.downtime_events:
        event_end = event.ended_at or window.end
        clipped = clip(Interval(event.started_at, event_end), window)
        if clipped is not None:
            seconds_by_reason[reason_names.get(event.reason_id, "Unknown")] += clipped.seconds
    downtime_total_seconds = sum(seconds_by_reason.values())
    top_reasons: list[DowntimeReasonSummary] = []
    cumulative_seconds = 0
    for reason, seconds in sorted(seconds_by_reason.items(), key=lambda item: (-item[1], item[0]))[
        :5
    ]:
        cumulative_seconds += seconds
        share = (
            Decimal(seconds) / Decimal(downtime_total_seconds)
            if downtime_total_seconds
            else Decimal("0")
        )
        cumulative_share = (
            Decimal(cumulative_seconds) / Decimal(downtime_total_seconds)
            if downtime_total_seconds
            else Decimal("0")
        )
        top_reasons.append(
            DowntimeReasonSummary(
                reason=reason,
                seconds=seconds,
                share=share,
                cumulative_share=cumulative_share,
            )
        )
    age = generated_at - data_through
    freshness: Literal["fresh", "stale"] = (
        "fresh" if age <= timedelta(minutes=settings.demo_freshness_minutes) else "stale"
    )
    return DemoOverviewResponse(
        generated_at=generated_at,
        data_through=data_through,
        freshness=freshness,
        line=DemoLine(id=line.id, code=line.code, name=line.name),
        window=DemoWindow(shift=shift_code, start=window.start, end=window.end),
        availability=snapshot.result.availability,
        performance_raw=snapshot.result.performance_raw,
        performance_capped=snapshot.result.performance_capped,
        quality=snapshot.result.quality,
        oee=snapshot.result.oee,
        planned_production_time_seconds=snapshot.result.planned_production_time_seconds,
        run_time_seconds=snapshot.result.run_time_seconds,
        total_count=snapshot.total_count,
        good_count=snapshot.good_count,
        rejected_count=snapshot.total_count - snapshot.good_count,
        downtime_total_events=len(snapshot.downtime_events),
        downtime_line_seconds=window.seconds - snapshot.result.run_time_seconds,
        downtime_logged_event_seconds=downtime_total_seconds,
        top_reasons=top_reasons,
        warnings=list(snapshot.warnings),
    )
