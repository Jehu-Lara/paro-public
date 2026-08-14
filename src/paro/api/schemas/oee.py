"""Output schema for ``GET /oee``.

The shape mirrors ``paro.domain.oee.OeeResult`` exactly (same fields, no
summarizing or renaming) plus query metadata (``line_id``,
``window_start``, ``window_end``). ``Decimal`` values are serialized as
strings so there's no ambiguity about whether they went through ``float``
at any point.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, field_serializer

from paro.domain.warnings import Warning

__all__ = ["OEEResponse"]

_DECIMAL_FIELDS = (
    "availability",
    "performance_raw",
    "performance_capped",
    "quality",
    "oee",
)


class OEEResponse(BaseModel):
    """OEE result for a given line and time window."""

    line_id: int
    window_start: datetime
    window_end: datetime

    availability: Decimal | None
    performance_raw: Decimal | None
    performance_capped: Decimal | None
    quality: Decimal | None
    oee: Decimal | None
    planned_production_time_seconds: int
    run_time_seconds: int
    warnings: list[Warning]

    @field_serializer(*_DECIMAL_FIELDS)
    def _serialize_decimal(self, value: Decimal | None) -> str | None:
        """Serializes as a string: never goes through ``float``, exact precision."""
        return None if value is None else str(value)
