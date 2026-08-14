"""Modelos SQLAlchemy del esquema operacional.

Portable entre SQLite y PostgreSQL a proposito: sin tipos ni ``server_default``
especificos de un dialecto, para que migrar sea solo cambiar la cadena de
conexion. ``rejected_count`` no se modela: es ``total_count - good_count``,
derivado siempre en el dominio para tener una sola fuente de verdad.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
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
    """Una linea de produccion dentro de la planta."""

    __tablename__ = "production_line"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Machine(Base):
    """Una maquina/estacion dentro de una linea."""

    __tablename__ = "machine"
    __table_args__ = (UniqueConstraint("line_id", "code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_line.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class DowntimeReason(Base):
    """Catalogo de causas de paro, con jerarquia opcional (causa/subcausa)."""

    __tablename__ = "downtime_reason"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("downtime_reason.id"), nullable=True)
    default_is_planned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Shift(Base):
    """Instancia concreta de un turno (sin recurrencia, ver README/Limitaciones)."""

    __tablename__ = "shift"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_line.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_start_utc: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    planned_end_utc: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    planned_break_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class DowntimeEvent(Base):
    """Evento de paro. ``ended_at is None`` representa un evento todavia abierto."""

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


class ProductionRecord(Base):
    """Conteo de produccion en un intervalo de tiempo para una linea."""

    __tablename__ = "production_record"
    __table_args__ = (
        CheckConstraint("interval_end > interval_start", name="valid_period"),
        CheckConstraint("good_count >= 0 AND good_count <= total_count", name="valid_counts"),
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
