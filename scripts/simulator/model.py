"""Draft row types the generator produces (docs/simulator-spec.md section 5).

Field-for-field matches to ``ProductionRecordCreate``/``DowntimeEventCreate``
(``src/paro/api/schemas/production.py``, ``src/paro/api/schemas/downtime.py``)
so a future transport step needs zero field mapping.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

__all__ = [
    "DowntimeEventDraft",
    "GeneratedRun",
    "LineConfig",
    "MachineConfig",
    "ProductionRecordDraft",
    "SimulatorConfig",
]


@dataclass(frozen=True)
class MachineConfig:
    machine_id: int
    line_id: int


@dataclass(frozen=True)
class LineConfig:
    line_id: int
    ideal_cycle_time_seconds: Decimal


@dataclass(frozen=True)
class SimulatorConfig:
    """Inputs the pure generator needs but can't derive itself (no DB/I/O).

    ``machines`` order doesn't need to be pre-sorted -- ``generate()`` sorts
    ascending by ``machine_id`` itself (simulator-spec.md section 3), and
    derives each line's bottleneck machine (lowest ``machine_id`` on that
    line) from this list rather than taking it as a separate, possibly
    inconsistent input.
    """

    lines: tuple[LineConfig, ...]
    machines: tuple[MachineConfig, ...]
    reason_ids: Mapping[str, int]  # downtime_reason.code -> DB id


@dataclass(frozen=True)
class ProductionRecordDraft:
    line_id: int
    interval_start: datetime
    interval_end: datetime
    total_count: int
    good_count: int
    ideal_cycle_time_seconds: Decimal
    source: str
    external_id: str


@dataclass(frozen=True)
class DowntimeEventDraft:
    line_id: int
    machine_id: int | None
    started_at: datetime
    ended_at: datetime | None
    reason_id: int
    is_planned: bool
    operator_note: str | None
    source: str
    external_id: str


@dataclass(frozen=True)
class GeneratedRun:
    production_records: tuple[ProductionRecordDraft, ...]
    downtime_events: tuple[DowntimeEventDraft, ...]
