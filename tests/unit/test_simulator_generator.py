"""Core generator structural invariants (docs/simulator-spec.md section 7,
SMOKE tier) -- this tests Step 3's own code, not the (future) QA Agent.

Scale matches the spec's own SMOKE run: 1 day x 2 machines (here, both on
one line, since production_record aggregation is per-line -- see the
implementation plan's resolved production_record-grain gap).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

import pytest
from scripts.simulator.config import (
    MICRO_STOP_FAILURE_BOUNDARY_SECONDS,
    REASON_CODES_BY_FAILURE_CLASS,
    REASON_CODES_BY_MICRO_STOP_CLASS,
    REASON_PLANNED_CHANGEOVER_CODE,
)
from scripts.simulator.generator import generate
from scripts.simulator.model import LineConfig, MachineConfig, SimulatorConfig

from paro.domain.intervals import Interval
from paro.domain.oee import DowntimeSpan, calculate_oee

_REASON_IDS = {
    REASON_PLANNED_CHANGEOVER_CODE: 1,
    REASON_CODES_BY_FAILURE_CLASS["mechanical"]: 2,
    REASON_CODES_BY_FAILURE_CLASS["electrical"]: 3,
    REASON_CODES_BY_FAILURE_CLASS["pneumatic"]: 4,
    REASON_CODES_BY_FAILURE_CLASS["sensor"]: 5,
    REASON_CODES_BY_MICRO_STOP_CLASS["material_jam"]: 6,
    REASON_CODES_BY_MICRO_STOP_CLASS["starvation"]: 7,
    REASON_CODES_BY_MICRO_STOP_CLASS["minor_adjustment"]: 8,
}
_FAILURE_REASON_IDS = {_REASON_IDS[code] for code in REASON_CODES_BY_FAILURE_CLASS.values()}
_MICRO_STOP_REASON_IDS = {_REASON_IDS[code] for code in REASON_CODES_BY_MICRO_STOP_CLASS.values()}
_PLANNED_REASON_ID = _REASON_IDS[REASON_PLANNED_CHANGEOVER_CODE]

_START = datetime(2026, 8, 10, 6, 0, tzinfo=UTC)  # aligned to shift A's start
_END = _START + timedelta(days=1)


def _smoke_config() -> SimulatorConfig:
    return SimulatorConfig(
        lines=(LineConfig(line_id=1, ideal_cycle_time_seconds=Decimal("30.000")),),
        machines=(
            MachineConfig(machine_id=1, line_id=1),
            MachineConfig(machine_id=2, line_id=1),
        ),
        reason_ids=_REASON_IDS,
    )


def test_generation_is_deterministic_for_the_same_seed() -> None:
    config = _smoke_config()

    first = generate(config, seed=42, start=_START, end=_END)
    second = generate(config, seed=42, start=_START, end=_END)

    assert first == second


def test_different_seeds_produce_different_output() -> None:
    config = _smoke_config()

    first = generate(config, seed=42, start=_START, end=_END)
    second = generate(config, seed=43, start=_START, end=_END)

    assert first != second


def test_no_overlapping_downtime_events_per_machine() -> None:
    run = generate(_smoke_config(), seed=42, start=_START, end=_END)

    by_machine: dict[int | None, list[tuple[datetime, datetime | None]]] = {}
    for event in run.downtime_events:
        by_machine.setdefault(event.machine_id, []).append((event.started_at, event.ended_at))

    for intervals in by_machine.values():
        intervals.sort()
        for (_, prev_end), (next_start, _) in pairwise(intervals):
            assert prev_end is not None
            assert next_start >= prev_end


def test_is_planned_matches_reason_class() -> None:
    run = generate(_smoke_config(), seed=42, start=_START, end=_END)

    for event in run.downtime_events:
        expected_planned = event.reason_id == _PLANNED_REASON_ID
        assert event.is_planned is expected_planned


def test_good_count_never_exceeds_total_count() -> None:
    run = generate(_smoke_config(), seed=42, start=_START, end=_END)

    for record in run.production_records:
        assert record.good_count <= record.total_count


def test_duration_matches_the_300_second_boundary() -> None:
    run = generate(_smoke_config(), seed=42, start=_START, end=_END)

    unplanned = [e for e in run.downtime_events if not e.is_planned]
    assert unplanned, "expected at least one unplanned event over a full smoke day"

    for event in unplanned:
        assert event.ended_at is not None
        duration = (event.ended_at - event.started_at).total_seconds()
        if duration < MICRO_STOP_FAILURE_BOUNDARY_SECONDS:
            assert event.reason_id in _MICRO_STOP_REASON_IDS
        else:
            assert event.reason_id in _FAILURE_REASON_IDS


def test_exactly_96_contiguous_buckets_with_no_gaps() -> None:
    run = generate(_smoke_config(), seed=42, start=_START, end=_END)

    records = sorted(run.production_records, key=lambda r: r.interval_start)
    assert len(records) == 96
    assert records[0].interval_start == _START
    assert records[-1].interval_end == _END
    for prev, curr in pairwise(records):
        assert prev.interval_end == curr.interval_start


def test_no_naive_datetimes_in_output() -> None:
    run = generate(_smoke_config(), seed=42, start=_START, end=_END)

    for record in run.production_records:
        assert record.interval_start.tzinfo is not None
        assert record.interval_end.tzinfo is not None
    for event in run.downtime_events:
        assert event.started_at.tzinfo is not None
        assert event.ended_at is None or event.ended_at.tzinfo is not None


def test_ideal_cycle_time_seconds_is_decimal_never_float() -> None:
    run = generate(_smoke_config(), seed=42, start=_START, end=_END)

    for record in run.production_records:
        assert isinstance(record.ideal_cycle_time_seconds, Decimal)


def test_multimachine_line_is_compatible_with_line_grain_oee() -> None:
    run = generate(_smoke_config(), seed=42, start=_START, end=_END)
    total_count = sum(record.total_count for record in run.production_records)
    good_count = sum(record.good_count for record in run.production_records)
    ideal_time = sum(
        (record.ideal_cycle_time_seconds * record.total_count for record in run.production_records),
        Decimal("0"),
    )
    result = calculate_oee(
        window=Interval(_START, _END),
        planned_downtimes=[
            DowntimeSpan(event.started_at, event.ended_at)
            for event in run.downtime_events
            if event.is_planned
        ],
        unplanned_downtimes=[
            DowntimeSpan(event.started_at, event.ended_at)
            for event in run.downtime_events
            if not event.is_planned
        ],
        total_count=total_count,
        good_count=good_count,
        ideal_time_total_seconds=ideal_time,
    )

    assert result.performance_raw is not None
    assert result.oee is not None
    assert Decimal("0") < result.performance_raw <= Decimal("1")
    assert Decimal("0") < result.oee <= Decimal("1")


def test_missing_reason_code_raises_before_generation() -> None:
    incomplete_ids = dict(_REASON_IDS)
    del incomplete_ids[REASON_PLANNED_CHANGEOVER_CODE]
    config = SimulatorConfig(
        lines=(LineConfig(line_id=1, ideal_cycle_time_seconds=Decimal("30.000")),),
        machines=(MachineConfig(machine_id=1, line_id=1),),
        reason_ids=incomplete_ids,
    )

    with pytest.raises(ValueError, match="reason_ids"):
        generate(config, seed=42, start=_START, end=_END)
