"""Schemas de entrada/salida para ``production_record``.

``rejected_count`` nunca se envia ni se guarda: es ``total_count -
good_count``, derivado en la respuesta con ``@computed_field`` para tener una
sola fuente de verdad (igual que ``db/models.py`` ya documenta).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_serializer,
    field_validator,
    model_validator,
)

__all__ = ["ProductionRecordCreate", "ProductionRecordResponse"]


def _require_aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} debe ser tz-aware; se recibio un datetime naive.")
    return value


class ProductionRecordCreate(BaseModel):
    """Payload de entrada para registrar un conteo de produccion."""

    line_id: int
    interval_start: datetime
    interval_end: datetime
    total_count: int = Field(ge=0)
    good_count: int = Field(ge=0)
    ideal_cycle_time_seconds: Decimal = Field(ge=0, max_digits=10, decimal_places=3)
    source: str | None = Field(default=None, min_length=1)
    external_id: str | None = Field(default=None, min_length=1)

    @field_validator("interval_start")
    @classmethod
    def _interval_start_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "interval_start")

    @field_validator("interval_end")
    @classmethod
    def _interval_end_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "interval_end")

    @model_validator(mode="after")
    def _validate_periods_and_counts(self) -> ProductionRecordCreate:
        if self.interval_end <= self.interval_start:
            raise ValueError("interval_end debe ser mayor que interval_start.")
        if self.good_count > self.total_count:
            raise ValueError(
                f"good_count ({self.good_count}) no puede superar total_count ({self.total_count})."
            )
        return self


class ProductionRecordResponse(BaseModel):
    """Representacion publica de un ``ProductionRecord`` persistido."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    line_id: int
    interval_start: datetime
    interval_end: datetime
    total_count: int
    good_count: int
    ideal_cycle_time_seconds: Decimal
    source: str | None
    external_id: str | None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def rejected_count(self) -> int:
        return self.total_count - self.good_count

    @field_serializer("ideal_cycle_time_seconds")
    def _serialize_decimal(self, value: Decimal) -> str:
        """Serializa como string: nunca pasa por ``float``, precision exacta."""
        return str(value)
