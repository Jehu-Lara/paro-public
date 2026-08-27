"""Input/output schemas for ``downtime_event``.

Naive timestamps are rejected here, at the HTTP boundary, with a Pydantic
422. If they were let through, ``UTCDateTime`` would reject them later
with an uncontrolled ``ValueError`` that would end up as a generic 500: an
invalid client input should never look like an internal failure.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = ["DowntimeEventCreate", "DowntimeEventPatch", "DowntimeEventResponse"]


def _require_aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} must be tz-aware; received a naive datetime.")
    return value


class DowntimeEventCreate(BaseModel):
    """Input payload to record a downtime event."""

    line_id: int
    machine_id: int | None = None
    started_at: datetime
    ended_at: datetime | None = None
    reason_id: int
    is_planned: bool
    operator_note: str | None = None
    source: str | None = Field(default=None, min_length=1, max_length=100)
    external_id: str | None = Field(default=None, min_length=1, max_length=200)

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
            raise ValueError("ended_at must be greater than started_at.")
        return self


class DowntimeEventPatch(BaseModel):
    """Partial correction of a persisted downtime event.

    ``expected_updated_at`` is the optimistic-concurrency token: it must
    match the row's current ``updated_at`` or the PATCH is rejected with a
    409 (see ``StaleUpdateError``). Every other field is optional and only
    applied when explicitly present in the request -- distinguished via
    Pydantic's ``model_fields_set``, not by a ``None`` default, since
    ``machine_id``/``operator_note``/``ended_at`` are themselves nullable
    columns a caller may legitimately want to clear.
    """

    expected_updated_at: datetime
    machine_id: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    reason_id: int | None = None
    is_planned: bool | None = None
    operator_note: str | None = None
    actor: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("expected_updated_at")
    @classmethod
    def _expected_updated_at_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "expected_updated_at")

    @field_validator("started_at")
    @classmethod
    def _started_at_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        return _require_aware(value, "started_at")

    @field_validator("ended_at")
    @classmethod
    def _ended_at_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        return _require_aware(value, "ended_at")


class DowntimeEventResponse(BaseModel):
    """Public representation of a persisted ``DowntimeEvent``."""

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
