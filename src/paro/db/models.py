"""SQLAlchemy models for the operational schema.

Portable between SQLite and PostgreSQL on purpose: no dialect-specific
types or ``server_default``, so migrating is just a matter of changing
the connection string. ``rejected_count`` isn't modeled: it's
``total_count - good_count``, always derived in the domain to keep a
single source of truth.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from paro.db.base import Base
from paro.db.types import UTCDateTime

__all__ = [
    "AuditLog",
    "DowntimeEvent",
    "DowntimeReason",
    "Machine",
    "ProductionLine",
    "ProductionRecord",
    "Shift",
]


def _now_utc() -> datetime:
    return datetime.now(UTC)


class ProductionLine(Base):
    """A production line within the plant."""

    __tablename__ = "production_line"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Machine(Base):
    """A machine/station within a line."""

    __tablename__ = "machine"
    __table_args__ = (UniqueConstraint("line_id", "code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_line.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class DowntimeReason(Base):
    """Catalog of downtime reasons, with optional hierarchy (cause/subcause)."""

    __tablename__ = "downtime_reason"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("downtime_reason.id"), nullable=True)
    default_is_planned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Shift(Base):
    """Concrete instance of a shift (no recurrence, see README/Limitations)."""

    __tablename__ = "shift"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_line.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_start_utc: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    planned_end_utc: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    planned_break_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class DowntimeEvent(Base):
    """A downtime event. ``ended_at is None`` represents an event still open."""

    __tablename__ = "downtime_event"
    __table_args__ = (
        CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="valid_period"),
        UniqueConstraint("source", "external_id"),
        Index("ix_downtime_event_line_id_started_at", "line_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_line.id"), nullable=False)
    machine_id: Mapped[int | None] = mapped_column(ForeignKey("machine.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reason_id: Mapped[int] = mapped_column(ForeignKey("downtime_reason.id"), nullable=False)
    is_planned: Mapped[bool] = mapped_column(Boolean, nullable=False)
    operator_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=_now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=_now_utc, onupdate=_now_utc
    )


class AuditLog(Base):
    """One row per PATCH that actually changed a ``downtime_event``.

    Scoped to ``downtime_event`` corrections only, not a generic
    polymorphic audit table -- see ``docs/downtime-corrections.md``.
    ``actor`` is free-text supplied by the caller, same trust level as
    ``downtime_event.operator_note``: real auth is separately out of scope,
    so it's not a verified identity.
    """

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_downtime_event_id", "downtime_event_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    downtime_event_id: Mapped[int] = mapped_column(ForeignKey("downtime_event.id"), nullable=False)
    changed_fields: Mapped[dict[str, list[Any]]] = mapped_column(JSON, nullable=False)
    actor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=_now_utc)


class ProductionRecord(Base):
    """A production count over a time interval for a line."""

    __tablename__ = "production_record"
    __table_args__ = (
        CheckConstraint("interval_end > interval_start", name="valid_period"),
        CheckConstraint("good_count >= 0 AND good_count <= total_count", name="valid_counts"),
        CheckConstraint("ideal_cycle_time_seconds >= 0", name="valid_ideal_cycle_time"),
        UniqueConstraint("source", "external_id"),
        Index("ix_production_record_line_id_interval_start", "line_id", "interval_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_line.id"), nullable=False)
    interval_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    interval_end: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False)
    good_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ideal_cycle_time_seconds: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=3, asdecimal=True), nullable=False
    )
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=_now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=_now_utc, onupdate=_now_utc
    )
