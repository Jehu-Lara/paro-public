"""Core event generator (docs/simulator-spec.md sections 1, 3, 4, 5).

``generate(config, seed, start, end) -> GeneratedRun`` is a pure function
(ADR 0004): no sleeps, no I/O, no network, no database access. Each
machine is simulated sequentially, in ascending ``machine_id`` order, off
its own RNG substream (section 3) -- machine *N*'s output never depends on
any other machine's. ``downtime_event`` stays per-machine. Production is
line-grained and modeled as a serial process: the lowest-ID machine is the
deterministic bottleneck clock, and a cycle is counted only when it does not
overlap a stop on any machine in the line. This keeps the generated counts
compatible with the line-grain OEE denominator.

Two implementation choices the spec leaves open, both documented at the
point they matter below: the planned changeover is placed at the start of
each shift (not spec-mandated -- Availability only depends on total
planned minutes, not their placement within the shift), and a cycle whose
drawn duration would overrun its shift window is dropped rather than
truncated (bounds "exactly 96 contiguous buckets, no gaps" cleanly, at the
cost of a few wasted seconds per shift -- negligible against every
acceptance band in section 8).
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

from scripts.simulator.config import (
    BOTTLENECK_FAILURE_RATE_MULTIPLIER,
    BOTTLENECK_MICRO_STOP_RATE_MULTIPLIER,
    CYCLE_TIME_MEAN_MULTIPLIER,
    CYCLE_TIME_SD_MULTIPLIER,
    CYCLE_TIME_TRUNC_MAX_MULTIPLIER,
    CYCLE_TIME_TRUNC_MIN_MULTIPLIER,
    FAILURE_DURATION_MAX_SECONDS,
    FAILURE_DURATION_MIN_SECONDS,
    FAILURE_DURATION_MU,
    FAILURE_DURATION_SIGMA,
    FAILURE_LAMBDA_PER_RUN_HOUR,
    MICRO_STOP_DURATION_MAX_SECONDS,
    MICRO_STOP_DURATION_MIN_SECONDS,
    MICRO_STOP_DURATION_MU,
    MICRO_STOP_DURATION_SIGMA,
    MICRO_STOP_LAMBDA_PER_RUN_HOUR,
    PLANNED_CHANGEOVER_DURATION_MAX_MINUTES,
    PLANNED_CHANGEOVER_DURATION_MIN_MINUTES,
    PRODUCTION_BUCKET_MINUTES,
    REASON_CODES_BY_FAILURE_CLASS,
    REASON_CODES_BY_MICRO_STOP_CLASS,
    REASON_MIX_FAILURE_CLASS,
    REASON_MIX_MICRO_STOP_CLASS,
    REASON_PLANNED_CHANGEOVER_CODE,
    SCRAP_PROBABILITY_BY_SHIFT,
    SERIAL_LINE_EVENT_RATE_FACTOR,
    SHIFT_BOUNDARIES_LOCAL,
    SHIFT_C_MICRO_STOP_RATE_MULTIPLIER,
    SHIFT_TIMEZONE,
    SOURCE,
    WARMUP_CYCLE_COUNT,
    WARMUP_CYCLE_TIME_MULTIPLIER,
    WARMUP_SCRAP_MULTIPLIER,
)
from scripts.simulator.model import (
    DowntimeEventDraft,
    GeneratedRun,
    LineConfig,
    MachineConfig,
    ProductionRecordDraft,
    SimulatorConfig,
)
from scripts.simulator.rng import machine_rng
from scripts.simulator.shift import shift_for

__all__ = ["generate"]

_TZ = ZoneInfo(SHIFT_TIMEZONE)
_ORDERED_SHIFT_BOUNDARIES = sorted(SHIFT_BOUNDARIES_LOCAL.items(), key=lambda item: item[1])

_REQUIRED_REASON_CODES = frozenset(
    {REASON_PLANNED_CHANGEOVER_CODE}
    | set(REASON_CODES_BY_FAILURE_CLASS.values())
    | set(REASON_CODES_BY_MICRO_STOP_CLASS.values())
)


@dataclass(frozen=True, slots=True)
class _Cycle:
    started_at: datetime
    ended_at: datetime
    is_good: bool


def generate(
    config: SimulatorConfig,
    seed: int,
    start: datetime,
    end: datetime,
    *,
    source: str = SOURCE,
    id_namespace: str | None = None,
) -> GeneratedRun:
    _validate(config, start, end)

    lines_by_id = {line.line_id: line for line in config.lines}
    machines_sorted = sorted(config.machines, key=lambda m: m.machine_id)
    bottleneck_machine_id_by_line = _bottleneck_machine_ids(machines_sorted)
    machine_count_by_line: dict[int, int] = {}
    for machine in machines_sorted:
        machine_count_by_line[machine.line_id] = machine_count_by_line.get(machine.line_id, 0) + 1

    downtime_events: list[DowntimeEventDraft] = []
    cycles_by_machine: dict[int, list[_Cycle]] = {}

    for machine in machines_sorted:
        line = lines_by_id[machine.line_id]
        is_bottleneck = bottleneck_machine_id_by_line[machine.line_id] == machine.machine_id
        machine_events, machine_cycles = _simulate_machine(
            machine=machine,
            t_seconds=float(line.ideal_cycle_time_seconds),
            is_bottleneck=is_bottleneck,
            event_rate_scale=(
                SERIAL_LINE_EVENT_RATE_FACTOR / machine_count_by_line[machine.line_id]
            ),
            reason_ids=config.reason_ids,
            rng=machine_rng(seed, machine.machine_id),
            start=start,
            end=end,
            source=source,
            id_namespace=id_namespace,
        )
        downtime_events.extend(machine_events)
        cycles_by_machine[machine.machine_id] = machine_cycles

    production_records: list[ProductionRecordDraft] = []
    for line in config.lines:
        bottleneck_id = bottleneck_machine_id_by_line[line.line_id]
        line_events = [event for event in downtime_events if event.line_id == line.line_id]
        line_cycles = [
            cycle
            for cycle in cycles_by_machine[bottleneck_id]
            if not _overlaps_any_event(cycle, line_events)
        ]
        production_records.extend(
            _bucket_line(
                line,
                line_cycles,
                start,
                end,
                source=source,
                id_namespace=id_namespace,
            )
        )

    production_records.sort(key=lambda r: (r.line_id, r.interval_start))
    downtime_events.sort(key=lambda e: (e.machine_id or 0, e.started_at))
    return GeneratedRun(
        production_records=tuple(production_records), downtime_events=tuple(downtime_events)
    )


def _overlaps_any_event(cycle: _Cycle, events: list[DowntimeEventDraft]) -> bool:
    return any(
        event.ended_at is not None
        and event.started_at < cycle.ended_at
        and event.ended_at > cycle.started_at
        for event in events
    )


def _validate(config: SimulatorConfig, start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start/end must be timezone-aware")
    if end <= start:
        raise ValueError("end must be after start")
    missing = _REQUIRED_REASON_CODES - set(config.reason_ids)
    if missing:
        raise ValueError(f"SimulatorConfig.reason_ids is missing required codes: {sorted(missing)}")
    line_ids = {line.line_id for line in config.lines}
    orphaned = {m.machine_id for m in config.machines if m.line_id not in line_ids}
    if orphaned:
        raise ValueError(f"machines reference unknown line_id(s): {sorted(orphaned)}")


def _bottleneck_machine_ids(machines_sorted: list[MachineConfig]) -> dict[int, int]:
    bottleneck: dict[int, int] = {}
    for machine in machines_sorted:
        bottleneck.setdefault(machine.line_id, machine.machine_id)
    return bottleneck


def _shift_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime, str]]:
    """``(boundary, window_end, shift_code)`` triples covering ``[start, end)``.

    ``boundary`` is the shift's true start in UTC (may be before ``start``
    for the first, already-in-progress shift); ``window_end`` is clipped to
    ``end``.
    """
    local_start = start.astimezone(_TZ)
    local_end = end.astimezone(_TZ)

    boundaries: list[datetime] = []
    day = local_start.date() - timedelta(days=1)
    last_day = local_end.date() + timedelta(days=1)
    while day <= last_day:
        for _, boundary_time in _ORDERED_SHIFT_BOUNDARIES:
            local_boundary = datetime.combine(day, boundary_time, tzinfo=_TZ)
            boundaries.append(local_boundary.astimezone(UTC))
        day += timedelta(days=1)
    boundaries.sort()

    windows: list[tuple[datetime, datetime, str]] = []
    for boundary, next_boundary in pairwise(boundaries):
        window_start = max(boundary, start)
        window_end = min(next_boundary, end)
        if window_start >= window_end:
            continue
        windows.append((boundary, window_end, shift_for(window_start)))
    return windows


def _simulate_machine(
    *,
    machine: MachineConfig,
    t_seconds: float,
    is_bottleneck: bool,
    event_rate_scale: float,
    reason_ids: Mapping[str, int],
    rng: random.Random,
    start: datetime,
    end: datetime,
    source: str,
    id_namespace: str | None,
) -> tuple[list[DowntimeEventDraft], list[_Cycle]]:
    events: list[DowntimeEventDraft] = []
    cycles: list[_Cycle] = []
    clock = start
    event_index = 0
    warmup_remaining = 0

    def emit(started_at: datetime, ended_at: datetime, reason_code: str, is_planned: bool) -> None:
        nonlocal event_index
        events.append(
            DowntimeEventDraft(
                line_id=machine.line_id,
                machine_id=machine.machine_id,
                started_at=started_at,
                ended_at=ended_at,
                reason_id=reason_ids[reason_code],
                is_planned=is_planned,
                operator_note=None,
                source=source,
                external_id=(
                    f"sim-{machine.machine_id}-{event_index}"
                    if id_namespace is None
                    else (
                        f"{id_namespace}:machine:{machine.machine_id}:event:"
                        f"{_absolute_id_timestamp(started_at)}:{event_index}"
                    )
                ),
            )
        )
        event_index += 1

    for boundary, window_end, shift_code in _shift_windows(start, end):
        if clock >= window_end:
            continue

        if boundary >= start:
            changeover_start = max(boundary, clock)
            duration_s = rng.uniform(
                PLANNED_CHANGEOVER_DURATION_MIN_MINUTES * 60,
                PLANNED_CHANGEOVER_DURATION_MAX_MINUTES * 60,
            )
            changeover_end = changeover_start + timedelta(seconds=duration_s)
            emit(changeover_start, changeover_end, REASON_PLANNED_CHANGEOVER_CODE, True)
            clock = changeover_end
            if clock >= window_end:
                continue

        while clock < window_end:
            mean = CYCLE_TIME_MEAN_MULTIPLIER * t_seconds
            sd = CYCLE_TIME_SD_MULTIPLIER * t_seconds
            lo = CYCLE_TIME_TRUNC_MIN_MULTIPLIER * t_seconds
            hi = CYCLE_TIME_TRUNC_MAX_MULTIPLIER * t_seconds
            cycle_time = _draw_truncated_normal(rng, mean, sd, lo, hi)
            if warmup_remaining > 0:
                cycle_time *= WARMUP_CYCLE_TIME_MULTIPLIER

            cycle_end = clock + timedelta(seconds=cycle_time)
            if cycle_end > window_end:
                break  # doesn't fit this shift; leave the tail ungenerated (see module docstring)

            scrap_p = SCRAP_PROBABILITY_BY_SHIFT[shift_code]
            if warmup_remaining > 0:
                scrap_p *= WARMUP_SCRAP_MULTIPLIER
            is_good = rng.random() >= scrap_p
            if warmup_remaining > 0:
                warmup_remaining -= 1

            cycles.append(_Cycle(started_at=clock, ended_at=cycle_end, is_good=is_good))
            clock = cycle_end

            mean_cycle = CYCLE_TIME_MEAN_MULTIPLIER * t_seconds
            failure_p = FAILURE_LAMBDA_PER_RUN_HOUR * event_rate_scale * mean_cycle / 3600
            if is_bottleneck:
                failure_p *= BOTTLENECK_FAILURE_RATE_MULTIPLIER

            if rng.random() < failure_p:
                duration = _draw_failure_duration(rng)
                reason_code = _draw_reason_code(
                    rng, REASON_MIX_FAILURE_CLASS, REASON_CODES_BY_FAILURE_CLASS
                )
                stoppage_end = clock + timedelta(seconds=duration)
                emit(clock, stoppage_end, reason_code, False)
                clock = stoppage_end
                warmup_remaining = WARMUP_CYCLE_COUNT
                continue

            micro_stop_p = MICRO_STOP_LAMBDA_PER_RUN_HOUR * event_rate_scale * mean_cycle / 3600
            if shift_code == "C":
                micro_stop_p *= SHIFT_C_MICRO_STOP_RATE_MULTIPLIER
            if is_bottleneck:
                micro_stop_p *= BOTTLENECK_MICRO_STOP_RATE_MULTIPLIER

            if rng.random() < micro_stop_p:
                duration = _draw_micro_stop_duration(rng)
                reason_code = _draw_reason_code(
                    rng, REASON_MIX_MICRO_STOP_CLASS, REASON_CODES_BY_MICRO_STOP_CLASS
                )
                stoppage_end = clock + timedelta(seconds=duration)
                emit(clock, stoppage_end, reason_code, False)
                clock = stoppage_end

    return events, cycles


def _draw_truncated_normal(
    rng: random.Random, mean: float, sd: float, lo: float, hi: float
) -> float:
    while True:
        value = rng.gauss(mean, sd)
        if lo <= value <= hi:
            return value


def _draw_micro_stop_duration(rng: random.Random) -> float:
    value = rng.lognormvariate(MICRO_STOP_DURATION_MU, MICRO_STOP_DURATION_SIGMA)
    return max(MICRO_STOP_DURATION_MIN_SECONDS, min(MICRO_STOP_DURATION_MAX_SECONDS, value))


def _draw_failure_duration(rng: random.Random) -> float:
    value = rng.lognormvariate(FAILURE_DURATION_MU, FAILURE_DURATION_SIGMA)
    return max(FAILURE_DURATION_MIN_SECONDS, min(FAILURE_DURATION_MAX_SECONDS, value))


def _draw_reason_code(
    rng: random.Random, class_weights: dict[str, float], code_by_key: dict[str, str]
) -> str:
    keys = list(class_weights.keys())
    weights = list(class_weights.values())
    chosen_key = rng.choices(keys, weights=weights, k=1)[0]
    return code_by_key[chosen_key]


def _bucket_line(
    line: LineConfig,
    cycles: list[_Cycle],
    start: datetime,
    end: datetime,
    *,
    source: str,
    id_namespace: str | None,
) -> list[ProductionRecordDraft]:
    bucket_seconds = PRODUCTION_BUCKET_MINUTES * 60
    num_buckets = int((end - start).total_seconds() // bucket_seconds)

    total_counts = [0] * num_buckets
    good_counts = [0] * num_buckets
    for cycle in cycles:
        index = int((cycle.ended_at - start).total_seconds() // bucket_seconds)
        if 0 <= index < num_buckets:
            total_counts[index] += 1
            if cycle.is_good:
                good_counts[index] += 1

    records: list[ProductionRecordDraft] = []
    for index in range(num_buckets):
        bucket_start = start + timedelta(seconds=index * bucket_seconds)
        bucket_end = bucket_start + timedelta(seconds=bucket_seconds)
        records.append(
            ProductionRecordDraft(
                line_id=line.line_id,
                interval_start=bucket_start,
                interval_end=bucket_end,
                total_count=total_counts[index],
                good_count=good_counts[index],
                ideal_cycle_time_seconds=line.ideal_cycle_time_seconds,
                source=source,
                external_id=(
                    f"sim-line{line.line_id}-{index}"
                    if id_namespace is None
                    else (
                        f"{id_namespace}:line:{line.line_id}:bucket:"
                        f"{_absolute_id_timestamp(bucket_start)}"
                    )
                ),
            )
        )
    return records


def _absolute_id_timestamp(value: datetime) -> str:
    """Compact UTC timestamp safe for deterministic external IDs."""
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
