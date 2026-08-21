"""QA Agent check functions (docs/simulator-spec.md sections 7-9).

One passing case and one deliberately-broken case per structural
invariant, mirroring tests/unit/test_simulator_generator.py's own style.
Also independently reproduces simulator-spec.md section 4.0's flat
baseline (62.54 micro-stops + 3.753 failures/machine-day) and section
4.5's chosen-topology figures (74.25 micro-stop + 4.33 failure
events/machine-day) from expected_unplanned_counts(), before trusting the
generic derivation against real generated data.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from scripts.simulator.config import (
    REASON_CODES_BY_FAILURE_CLASS,
    REASON_CODES_BY_MICRO_STOP_CLASS,
    REASON_PLANNED_CHANGEOVER_CODE,
)
from scripts.simulator.generator import generate
from scripts.simulator.model import (
    DowntimeEventDraft,
    GeneratedRun,
    LineConfig,
    MachineConfig,
    ProductionRecordDraft,
    SimulatorConfig,
)
from scripts.simulator.qa import (
    _machine_shift_unplanned_stats,
    check_idempotency,
    check_statistical_bands,
    check_structural,
    expected_unplanned_counts,
)
from scripts.simulator.transport import TransportResult

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
_PLANNED_REASON_ID = _REASON_IDS[REASON_PLANNED_CHANGEOVER_CODE]
_MECHANICAL_REASON_ID = _REASON_IDS[REASON_CODES_BY_FAILURE_CLASS["mechanical"]]
_REASON_PLANNED_BY_ID = {
    1: True,
    2: False,
    3: False,
    4: False,
    5: False,
    6: False,
    7: False,
    8: False,
}

_START = datetime(2026, 8, 10, 6, 0, tzinfo=UTC)
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


def _two_line_topology() -> SimulatorConfig:
    """The real 2-line x 4-machine topology scripts/simulate_production.py
    builds (SIM-L1/SIM-L2 x M1-M4), rebuilt with plain sequential ids here
    since only the shape -- not the DB rows -- matters for this check.
    """
    lines = tuple(
        LineConfig(line_id=line_id, ideal_cycle_time_seconds=Decimal("30.000"))
        for line_id in (1, 2)
    )
    machines = tuple(
        MachineConfig(machine_id=machine_id, line_id=line_id)
        for line_id in (1, 2)
        for machine_id in range(1, 5)
    )
    return SimulatorConfig(lines=lines, machines=machines, reason_ids=_REASON_IDS)


def _production_record(
    *, line_id: int = 1, total_count: int = 10, good_count: int = 9, external_id: str = "pr-1"
) -> ProductionRecordDraft:
    return ProductionRecordDraft(
        line_id=line_id,
        interval_start=_START,
        interval_end=_START + timedelta(minutes=15),
        total_count=total_count,
        good_count=good_count,
        ideal_cycle_time_seconds=Decimal("30.000"),
        source="simulator",
        external_id=external_id,
    )


def _downtime_event(
    *,
    machine_id: int | None = 1,
    started_at: datetime = _START,
    ended_at: datetime | None = _START + timedelta(seconds=60),
    reason_id: int = 6,
    is_planned: bool = False,
    external_id: str = "de-1",
) -> DowntimeEventDraft:
    return DowntimeEventDraft(
        line_id=1,
        machine_id=machine_id,
        started_at=started_at,
        ended_at=ended_at,
        reason_id=reason_id,
        is_planned=is_planned,
        operator_note=None,
        source="simulator",
        external_id=external_id,
    )


# ---- check_structural -------------------------------------------------


def test_check_structural_passes_on_real_generated_smoke_run() -> None:
    run = generate(_smoke_config(), seed=42, start=_START, end=_END)

    findings = check_structural(
        run, _smoke_config(), _START, _END, reason_planned_by_id=_REASON_PLANNED_BY_ID
    )

    assert findings == []


def test_check_structural_flags_overlapping_downtime_events() -> None:
    run = GeneratedRun(
        production_records=(),
        downtime_events=(
            _downtime_event(
                external_id="de-1", started_at=_START, ended_at=_START + timedelta(minutes=10)
            ),
            _downtime_event(
                external_id="de-2",
                started_at=_START + timedelta(minutes=5),
                ended_at=_START + timedelta(minutes=15),
            ),
        ),
    )

    findings = check_structural(
        run, _smoke_config(), _START, _END, reason_planned_by_id=_REASON_PLANNED_BY_ID
    )

    assert any(f.check == "overlapping_downtime_events" for f in findings)


def test_check_structural_flags_is_planned_mismatch() -> None:
    run = GeneratedRun(
        production_records=(),
        downtime_events=(_downtime_event(reason_id=_MECHANICAL_REASON_ID, is_planned=True),),
    )

    findings = check_structural(
        run, _smoke_config(), _START, _END, reason_planned_by_id=_REASON_PLANNED_BY_ID
    )

    assert any(f.check == "is_planned_mismatch" for f in findings)


def test_check_structural_flags_unknown_reason_id() -> None:
    run = GeneratedRun(
        production_records=(),
        downtime_events=(_downtime_event(reason_id=999),),
    )

    findings = check_structural(
        run, _smoke_config(), _START, _END, reason_planned_by_id=_REASON_PLANNED_BY_ID
    )

    assert any(f.check == "unknown_reason_id" for f in findings)
    assert not any(f.check == "is_planned_mismatch" for f in findings)


def test_check_structural_flags_good_count_exceeding_total() -> None:
    run = GeneratedRun(
        production_records=(_production_record(total_count=5, good_count=6),), downtime_events=()
    )

    findings = check_structural(
        run, _smoke_config(), _START, _END, reason_planned_by_id=_REASON_PLANNED_BY_ID
    )

    assert any(f.check == "good_count_exceeds_total" for f in findings)


def test_check_structural_flags_boundary_mismatch() -> None:
    long_micro_stop = _downtime_event(
        reason_id=6, ended_at=_START + timedelta(seconds=400)
    )  # >=300s but tagged micro-stop
    run = GeneratedRun(production_records=(), downtime_events=(long_micro_stop,))

    findings = check_structural(
        run, _smoke_config(), _START, _END, reason_planned_by_id=_REASON_PLANNED_BY_ID
    )

    assert any(f.check == "boundary_mismatch" for f in findings)


def test_check_structural_flags_naive_timestamp() -> None:
    naive_record = ProductionRecordDraft(
        line_id=1,
        interval_start=datetime(2026, 8, 10, 6, 0),
        interval_end=datetime(2026, 8, 10, 6, 15),
        total_count=1,
        good_count=1,
        ideal_cycle_time_seconds=Decimal("30.000"),
        source="simulator",
        external_id="pr-naive",
    )
    run = GeneratedRun(production_records=(naive_record,), downtime_events=())

    findings = check_structural(
        run, _smoke_config(), _START, _END, reason_planned_by_id=_REASON_PLANNED_BY_ID
    )

    assert any(f.check == "naive_timestamp" for f in findings)


def test_check_structural_flags_bucket_count_mismatch() -> None:
    run = GeneratedRun(production_records=(_production_record(),), downtime_events=())

    findings = check_structural(
        run, _smoke_config(), _START, _END, reason_planned_by_id=_REASON_PLANNED_BY_ID
    )

    assert any(f.check == "bucket_count_mismatch" for f in findings)


# ---- check_idempotency --------------------------------------------------


def test_check_idempotency_passes_when_second_run_adds_nothing() -> None:
    first = TransportResult(
        production_records_created=5,
        production_records_existing=0,
        downtime_events_created=3,
        downtime_events_existing=0,
        failures=(),
    )
    second = TransportResult(
        production_records_created=0,
        production_records_existing=5,
        downtime_events_created=0,
        downtime_events_existing=3,
        failures=(),
    )

    assert check_idempotency(first, second) == []


def test_check_idempotency_flags_new_rows_on_repeat() -> None:
    first = TransportResult(
        production_records_created=5,
        production_records_existing=0,
        downtime_events_created=3,
        downtime_events_existing=0,
        failures=(),
    )
    second = TransportResult(
        production_records_created=1,
        production_records_existing=4,
        downtime_events_created=0,
        downtime_events_existing=3,
        failures=(),
    )

    findings = check_idempotency(first, second)

    assert any(f.check == "production_records_created_on_repeat" for f in findings)


# ---- expected_unplanned_counts ------------------------------------------


def test_flat_baseline_reproduces_section_4_0() -> None:
    micro_stops_a, failures_a = _machine_shift_unplanned_stats(is_bottleneck=False, shift_code="A")

    assert 3 * micro_stops_a == pytest.approx(62.54, rel=1e-3)
    assert 3 * failures_a == pytest.approx(3.753, rel=1e-3)


def test_chosen_topology_reproduces_section_4_5() -> None:
    config = _two_line_topology()

    expected = expected_unplanned_counts(config, days=1)

    per_line_micro_stops = expected.micro_stop_count / len(config.lines)
    per_line_failures = expected.failure_count / len(config.lines)
    assert per_line_micro_stops == pytest.approx(68.81, rel=5e-3)
    assert per_line_failures == pytest.approx(4.030, rel=5e-3)


# ---- check_statistical_bands ---------------------------------------------


def test_check_statistical_bands_flags_oee_null() -> None:
    run = GeneratedRun(production_records=(), downtime_events=())

    findings = check_statistical_bands(run, _smoke_config(), days=1, oee_by_line={1: None})

    assert any(f.check == "oee_null" for f in findings)


def test_check_statistical_bands_flags_oee_out_of_band() -> None:
    run = GeneratedRun(production_records=(), downtime_events=())

    findings = check_statistical_bands(
        run, _smoke_config(), days=1, oee_by_line={1: Decimal("0.50")}
    )

    assert any(f.check == "oee_out_of_band" for f in findings)


def test_check_statistical_bands_passes_oee_in_band() -> None:
    run = GeneratedRun(production_records=(), downtime_events=())

    findings = check_statistical_bands(
        run, _smoke_config(), days=1, oee_by_line={1: Decimal("0.75")}
    )

    assert not any(f.check == "oee_out_of_band" or f.check == "oee_null" for f in findings)
