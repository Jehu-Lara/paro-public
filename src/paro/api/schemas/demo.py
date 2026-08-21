"""Public read model for the synthetic live-updating portfolio demo."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, field_serializer

from paro.domain.warnings import Warning

__all__ = ["DemoOverviewResponse"]


class DemoLine(BaseModel):
    id: int
    code: str
    name: str


class DemoWindow(BaseModel):
    shift: Literal["A", "B", "C"]
    start: datetime
    end: datetime


class DowntimeReasonSummary(BaseModel):
    reason: str
    seconds: int
    share: Decimal
    cumulative_share: Decimal

    @field_serializer("share", "cumulative_share")
    def _serialize_share(self, value: Decimal) -> str:
        return str(value)


class DemoOverviewResponse(BaseModel):
    generated_at: datetime
    data_through: datetime
    freshness: Literal["fresh", "stale"]
    synthetic: Literal[True] = True
    refresh_cadence_minutes: Literal[15] = 15
    line: DemoLine
    window: DemoWindow
    availability: Decimal | None
    performance_raw: Decimal | None
    performance_capped: Decimal | None
    quality: Decimal | None
    oee: Decimal | None
    planned_production_time_seconds: int
    run_time_seconds: int
    total_count: int
    good_count: int
    rejected_count: int
    downtime_total_events: int
    downtime_line_seconds: int
    downtime_logged_event_seconds: int
    top_reasons: list[DowntimeReasonSummary]
    warnings: list[Warning]

    @field_serializer("availability", "performance_raw", "performance_capped", "quality", "oee")
    def _serialize_decimal(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)
