"""Schemas de entrada/salida para ``downtime_event``.

Los timestamps naive se rechazan aqui, en la frontera HTTP, con un 422 de
Pydantic. Si se dejaran pasar, ``UTCDateTime`` los rechazaria mas tarde con un
``ValueError`` sin controlar que terminaria como un 500 generico: un dato de
entrada invalido del cliente nunca deberia parecer un fallo interno.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = ["DowntimeEventCreate", "DowntimeEventResponse"]


def _require_aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} debe ser tz-aware; se recibio un datetime naive.")
    return value


class DowntimeEventCreate(BaseModel):
    """Payload de entrada para registrar un evento de paro."""

    line_id: int
    machine_id: int | None = None
    started_at: datetime
    ended_at: datetime | None = None
    reason_id: int
    is_planned: bool
    operator_note: str | None = None
    source: str | None = Field(default=None, min_length=1)
    external_id: str | None = Field(default=None, min_length=1)

    @field_validator("started_at")
    @classmethod
    def _started_at_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "started_at")

    @field_validator("ended_at")
    @classmethod
    def _ended_at_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        return _require_aware(value, "ended_at")

    @model_validator(mode="after")
    def _ended_after_started(self) -> DowntimeEventCreate:
        if self.ended_at is not None and self.ended_at <= self.started_at:
            raise ValueError("ended_at debe ser mayor que started_at.")
        return self


class DowntimeEventResponse(BaseModel):
    """Representacion publica de un ``DowntimeEvent`` persistido."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    line_id: int
    machine_id: int | None
    started_at: datetime
    ended_at: datetime | None
    reason_id: int
    is_planned: bool
    operator_note: str | None
    source: str | None
    external_id: str | None
    created_at: datetime
    updated_at: datetime
