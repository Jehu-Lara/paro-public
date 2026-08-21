"""QA Agent checks (docs/simulator-spec.md sections 7-9;
docs/adr/0004-simulator-multi-agent-architecture.md's 2026-08-18
revision -- QA checks only, no Developer Agent/LangGraph/Ollama).

Structural and idempotency checks are pure. Statistical band checks
compute their expected center generically from this package's own
lambda/multiplier constants and whatever topology ``SimulatorConfig``
holds, per the derivation in the implementation plan -- not the spec's
own hand-derived 25%-bottleneck numbers -- so they stay correct if the
topology ever changes without a second, independently maintained copy of
derived figures.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from math import exp
from typing import Literal

from paro.domain.intervals import Interval, clip, duration_seconds
from scripts.simulator.config import (
    ACCEPTANCE_BAND_CYCLE_TIME_RELATIVE,
    ACCEPTANCE_BAND_FAILURE_RELATIVE,
    ACCEPTANCE_BAND_MICRO_STOP_RELATIVE,
    ACCEPTANCE_BAND_OEE_MAX,
    ACCEPTANCE_BAND_OEE_MIN,
    ACCEPTANCE_BAND_REASON_MIX_RELATIVE,
    ACCEPTANCE_BAND_SCRAP_PP,
    BOTTLENECK_FAILURE_RATE_MULTIPLIER,
    BOTTLENECK_MICRO_STOP_RATE_MULTIPLIER,
    CYCLE_TIME_MEAN_MULTIPLIER,
    FAILURE_DURATION_MU,
    FAILURE_DURATION_SIGMA,
    FAILURE_LAMBDA_PER_RUN_HOUR,
    MICRO_STOP_DURATION_MU,
    MICRO_STOP_DURATION_SIGMA,
    MICRO_STOP_FAILURE_BOUNDARY_SECONDS,
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
    SHIFT_C_MICRO_STOP_RATE_MULTIPLIER,
)
from scripts.simulator.generator import _bottleneck_machine_ids
from scripts.simulator.model import GeneratedRun, ProductionRecordDraft, SimulatorConfig
from scripts.simulator.transport import TransportResult

__all__ = [
    "ExpectedCounts",
    "Finding",
    "check_idempotency",
    "check_statistical_bands",
    "check_structural",
    "expected_unplanned_counts",
]

_SHIFT_MINUTES = 480
_CHANGEOVER_MEAN_MINUTES = (
    PLANNED_CHANGEOVER_DURATION_MIN_MINUTES + PLANNED_CHANGEOVER_DURATION_MAX_MINUTES
) / 2
_PPT_SHIFT_SECONDS = (_SHIFT_MINUTES - _CHANGEOVER_MEAN_MINUTES) * 60


@dataclass(frozen=True)
class Finding:
    tier: Literal["structural", "idempotency", "statistical"]
    check: str
    detail: str


@dataclass(frozen=True)
class ExpectedCounts:
    micro_stop_count: float
    failure_count: float


def _reason_class_and_key_by_id(config: SimulatorConfig) -> dict[int, tuple[str, str]]:
    """``reason_id -> (class, key)``, e.g. ``5 -> ("failure", "mechanical")``.

    Built from ``config.reason_ids`` (code -> id) plus this module's own
    class/key catalogs -- classification isn't a DB concept (no column
    for it), so there's no "real" catalog to cross-check against, unlike
    ``default_is_planned`` below.
    """
    result: dict[int, tuple[str, str]] = {}
    for key, code in REASON_CODES_BY_FAILURE_CLASS.items():
        reason_id = config.reason_ids.get(code)
        if reason_id is not None:
            result[reason_id] = ("failure", key)
    for key, code in REASON_CODES_BY_MICRO_STOP_CLASS.items():
        reason_id = config.reason_ids.get(code)
        if reason_id is not None:
            result[reason_id] = ("micro_stop", key)
    planned_id = config.reason_ids.get(REASON_PLANNED_CHANGEOVER_CODE)
    if planned_id is not None:
        result[planned_id] = ("planned", "planned_changeover")
    return result


def check_structural(
    run: GeneratedRun,
    config: SimulatorConfig,
    start: datetime,
    end: datetime,
    reason_planned_by_id: Mapping[int, bool],
) -> list[Finding]:
    """All of simulator-spec.md section 7's SMOKE structural invariants,
    checked against the pre-transport generated event stream.

    ``start``/``end`` (not a ``days`` count) drive the expected bucket
    count -- the same ``[start, end)`` window ``generate()`` itself took,
    so this works for any window length, not just whole-day ones. This
    matters for tests that need a fast, small window rather than a full
    simulated day (568 real HTTP+DB round trips at true SMOKE scale --
    96 production_records + ~188 downtime_events, doubled for idempotency
    -- took 17 minutes against a real TestClient/SQLite DB in practice).
    """
    findings: list[Finding] = []
    reason_class_by_id = _reason_class_and_key_by_id(config)

    by_machine: dict[int | None, list[tuple[datetime, datetime | None]]] = {}
    for event in run.downtime_events:
        by_machine.setdefault(event.machine_id, []).append((event.started_at, event.ended_at))
    for machine_id, intervals in by_machine.items():
        intervals.sort(key=lambda interval: interval[0])
        for (_, prev_end), (next_start, _) in pairwise(intervals):
            if prev_end is None:
                continue
            if next_start < prev_end:
                findings.append(
                    Finding(
                        "structural",
                        "overlapping_downtime_events",
                        f"machine {machine_id}: overlap around {next_start}",
                    )
                )

    for event in run.downtime_events:
        expected_planned = reason_planned_by_id.get(event.reason_id)
        if expected_planned is None:
            findings.append(
                Finding(
                    "structural",
                    "unknown_reason_id",
                    f"downtime_event {event.external_id} references unknown "
                    f"reason_id {event.reason_id}",
                )
            )
            continue
        if event.is_planned != expected_planned:
            findings.append(
                Finding(
                    "structural",
                    "is_planned_mismatch",
                    f"downtime_event {event.external_id}: is_planned={event.is_planned} "
                    f"but catalog default_is_planned={expected_planned}",
                )
            )

        if event.ended_at is None:
            continue
        duration = (event.ended_at - event.started_at).total_seconds()
        reason_class = reason_class_by_id.get(event.reason_id, ("unknown", "unknown"))[0]
        if reason_class == "planned":
            continue
        expected_class = (
            "micro_stop" if duration < MICRO_STOP_FAILURE_BOUNDARY_SECONDS else "failure"
        )
        if reason_class != expected_class:
            findings.append(
                Finding(
                    "structural",
                    "boundary_mismatch",
                    f"downtime_event {event.external_id}: duration={duration}s, "
                    f"reason_class={reason_class}, expected={expected_class}",
                )
            )

    for record in run.production_records:
        if record.good_count > record.total_count:
            findings.append(
                Finding(
                    "structural",
                    "good_count_exceeds_total",
                    f"production_record {record.external_id}: good_count={record.good_count} "
                    f"> total_count={record.total_count}",
                )
            )

    bucket_seconds = PRODUCTION_BUCKET_MINUTES * 60
    expected_buckets_per_line = int((end - start).total_seconds()) // bucket_seconds
    records_by_line: dict[int, list[ProductionRecordDraft]] = {}
    for record in run.production_records:
        records_by_line.setdefault(record.line_id, []).append(record)
    for line_id, records in records_by_line.items():
        records.sort(key=lambda r: r.interval_start)
        if len(records) != expected_buckets_per_line:
            findings.append(
                Finding(
                    "structural",
                    "bucket_count_mismatch",
                    f"line {line_id}: {len(records)} production_records, "
                    f"expected {expected_buckets_per_line}",
                )
            )
        for record in records:
            span = (record.interval_end - record.interval_start).total_seconds()
            if span != bucket_seconds:
                findings.append(
                    Finding(
                        "structural",
                        "bucket_misaligned",
                        f"production_record {record.external_id} span={span}s, "
                        f"expected {bucket_seconds}s",
                    )
                )
        for prev, curr in pairwise(records):
            if prev.interval_end != curr.interval_start:
                findings.append(
                    Finding(
                        "structural",
                        "bucket_gap",
                        f"line {line_id}: gap/overlap between "
                        f"{prev.external_id} and {curr.external_id}",
                    )
                )

    for record in run.production_records:
        if record.interval_start.tzinfo is None or record.interval_end.tzinfo is None:
            findings.append(
                Finding(
                    "structural",
                    "naive_timestamp",
                    f"production_record {record.external_id} has a naive timestamp",
                )
            )
    for event in run.downtime_events:
        if event.started_at.tzinfo is None or (
            event.ended_at is not None and event.ended_at.tzinfo is None
        ):
            findings.append(
                Finding(
                    "structural",
                    "naive_timestamp",
                    f"downtime_event {event.external_id} has a naive timestamp",
                )
            )

    return findings


def check_idempotency(after_first: TransportResult, after_second: TransportResult) -> list[Finding]:
    """The second identical transport() must resolve everything the first
    one wrote as an existing no-op -- nothing created, nothing lost.
    """
    findings: list[Finding] = []
    if after_second.production_records_created != 0:
        findings.append(
            Finding(
                "idempotency",
                "production_records_created_on_repeat",
                f"{after_second.production_records_created} new production_records on re-run",
            )
        )
    if after_second.downtime_events_created != 0:
        findings.append(
            Finding(
                "idempotency",
                "downtime_events_created_on_repeat",
                f"{after_second.downtime_events_created} new downtime_events on re-run",
            )
        )
    expected_pr_existing = (
        after_first.production_records_created + after_first.production_records_existing
    )
    if after_second.production_records_existing != expected_pr_existing:
        findings.append(
            Finding(
                "idempotency",
                "production_records_existing_mismatch",
                f"observed={after_second.production_records_existing} "
                f"expected={expected_pr_existing}",
            )
        )
    expected_de_existing = (
        after_first.downtime_events_created + after_first.downtime_events_existing
    )
    if after_second.downtime_events_existing != expected_de_existing:
        findings.append(
            Finding(
                "idempotency",
                "downtime_events_existing_mismatch",
                f"observed={after_second.downtime_events_existing} expected={expected_de_existing}",
            )
        )
    return findings


def _mean_lognormal(mu: float, sigma: float) -> float:
    return exp(mu + sigma**2 / 2)


def _machine_shift_unplanned_stats(
    *, is_bottleneck: bool, shift_code: str, event_rate_scale: float = 1.0
) -> tuple[float, float]:
    """``(expected_micro_stops, expected_failures)`` for one machine over one
    8h shift -- simulator-spec.md section 4.0's per-shift decomposition,
    generalized with the bottleneck/shift-C multipliers section 4.5 adds.
    """
    mean_micro_stop_duration = _mean_lognormal(MICRO_STOP_DURATION_MU, MICRO_STOP_DURATION_SIGMA)
    mean_failure_duration = _mean_lognormal(FAILURE_DURATION_MU, FAILURE_DURATION_SIGMA)

    micro_stop_lambda = MICRO_STOP_LAMBDA_PER_RUN_HOUR * event_rate_scale
    if shift_code == "C":
        micro_stop_lambda *= SHIFT_C_MICRO_STOP_RATE_MULTIPLIER
    if is_bottleneck:
        micro_stop_lambda *= BOTTLENECK_MICRO_STOP_RATE_MULTIPLIER

    failure_lambda = FAILURE_LAMBDA_PER_RUN_HOUR * event_rate_scale
    if is_bottleneck:
        failure_lambda *= BOTTLENECK_FAILURE_RATE_MULTIPLIER

    ud_over_r = (
        micro_stop_lambda * mean_micro_stop_duration + failure_lambda * mean_failure_duration
    ) / 3600
    run_time_seconds = _PPT_SHIFT_SECONDS / (1 + ud_over_r)
    micro_stops = (run_time_seconds / 3600) * micro_stop_lambda
    failures = (run_time_seconds / 3600) * failure_lambda
    return micro_stops, failures


def expected_unplanned_counts(config: SimulatorConfig, days: int) -> ExpectedCounts:
    machines_sorted = sorted(config.machines, key=lambda m: m.machine_id)
    bottleneck_machine_id_by_line = _bottleneck_machine_ids(machines_sorted)

    total_micro_stops = 0.0
    total_failures = 0.0
    machines_per_line: dict[int, int] = {}
    for machine in machines_sorted:
        machines_per_line[machine.line_id] = machines_per_line.get(machine.line_id, 0) + 1
    for machine in machines_sorted:
        is_bottleneck = bottleneck_machine_id_by_line[machine.line_id] == machine.machine_id
        for shift_code in ("A", "B", "C"):
            micro_stops, failures = _machine_shift_unplanned_stats(
                is_bottleneck=is_bottleneck,
                shift_code=shift_code,
                event_rate_scale=(
                    SERIAL_LINE_EVENT_RATE_FACTOR / machines_per_line[machine.line_id]
                ),
            )
            total_micro_stops += micro_stops
            total_failures += failures

    return ExpectedCounts(
        micro_stop_count=total_micro_stops * days,
        failure_count=total_failures * days,
    )


def _check_relative_band(
    findings: list[Finding], check: str, observed: float, expected: float, relative_band: float
) -> None:
    if expected == 0:
        return
    relative_error = abs(observed - expected) / expected
    if relative_error > relative_band:
        findings.append(
            Finding(
                "statistical",
                check,
                f"observed={observed:.2f} expected={expected:.2f} "
                f"relative_error={relative_error:.3f} band=+/-{relative_band}",
            )
        )


def check_statistical_bands(
    run: GeneratedRun,
    config: SimulatorConfig,
    days: int,
    oee_by_line: Mapping[int, Decimal | None],
) -> list[Finding]:
    """simulator-spec.md section 8's ACCEPTANCE-tier statistical bands."""
    findings: list[Finding] = []

    total_count = sum(record.total_count for record in run.production_records)
    good_count = sum(record.good_count for record in run.production_records)
    if total_count > 0:
        observed_scrap = 1 - (good_count / total_count)
        expected_scrap = sum(SCRAP_PROBABILITY_BY_SHIFT.values()) / len(SCRAP_PROBABILITY_BY_SHIFT)
        if abs(observed_scrap - expected_scrap) > ACCEPTANCE_BAND_SCRAP_PP:
            findings.append(
                Finding(
                    "statistical",
                    "scrap_rate_out_of_band",
                    f"observed={observed_scrap:.4f} expected={expected_scrap:.4f} "
                    f"band=+/-{ACCEPTANCE_BAND_SCRAP_PP}pp",
                )
            )

    reason_class_by_id = _reason_class_and_key_by_id(config)
    unplanned = [event for event in run.downtime_events if not event.is_planned]
    durations_by_key: dict[str, float] = {}
    observed_micro_stops = 0
    observed_failures = 0
    for event in unplanned:
        if event.ended_at is None:
            continue
        duration = (event.ended_at - event.started_at).total_seconds()
        reason_class, key = reason_class_by_id.get(event.reason_id, ("unknown", "unknown"))
        durations_by_key[key] = durations_by_key.get(key, 0.0) + duration
        if reason_class == "micro_stop":
            observed_micro_stops += 1
        elif reason_class == "failure":
            observed_failures += 1

    expected = expected_unplanned_counts(config, days)
    _check_relative_band(
        findings,
        "micro_stop_rate_out_of_band",
        observed_micro_stops,
        expected.micro_stop_count,
        ACCEPTANCE_BAND_MICRO_STOP_RELATIVE,
    )
    _check_relative_band(
        findings,
        "failure_rate_out_of_band",
        observed_failures,
        expected.failure_count,
        ACCEPTANCE_BAND_FAILURE_RELATIVE,
    )

    mean_micro_stop_duration = _mean_lognormal(MICRO_STOP_DURATION_MU, MICRO_STOP_DURATION_SIGMA)
    mean_failure_duration = _mean_lognormal(FAILURE_DURATION_MU, FAILURE_DURATION_SIGMA)
    expected_micro_stop_minutes = expected.micro_stop_count * mean_micro_stop_duration / 60
    expected_failure_minutes = expected.failure_count * mean_failure_duration / 60
    expected_total_minutes = expected_micro_stop_minutes + expected_failure_minutes
    observed_total_minutes = sum(durations_by_key.values()) / 60
    if expected_total_minutes > 0 and observed_total_minutes > 0:
        class_expected_share = {
            "micro_stop": expected_micro_stop_minutes / expected_total_minutes,
            "failure": expected_failure_minutes / expected_total_minutes,
        }
        for class_label, within_class in (
            ("failure", REASON_MIX_FAILURE_CLASS),
            ("micro_stop", REASON_MIX_MICRO_STOP_CLASS),
        ):
            for key, within_class_share in within_class.items():
                expected_share = class_expected_share[class_label] * within_class_share
                observed_share = durations_by_key.get(key, 0.0) / 60 / observed_total_minutes
                _check_relative_band(
                    findings,
                    f"reason_mix_out_of_band_{key}",
                    observed_share,
                    expected_share,
                    ACCEPTANCE_BAND_REASON_MIX_RELATIVE,
                )

    cycles_by_line: dict[int, int] = {}
    for record in run.production_records:
        cycles_by_line[record.line_id] = cycles_by_line.get(record.line_id, 0) + record.total_count
    if run.production_records:
        window_start = min(record.interval_start for record in run.production_records)
        window_end = max(record.interval_end for record in run.production_records)
        simulation_window = Interval(window_start, window_end)
        for line in config.lines:
            cycles = cycles_by_line.get(line.line_id, 0)
            if cycles == 0:
                continue
            line_stops = [
                clipped
                for event in run.downtime_events
                if event.line_id == line.line_id and event.ended_at is not None
                for clipped in [clip(Interval(event.started_at, event.ended_at), simulation_window)]
                if clipped is not None
            ]
            run_time_seconds = simulation_window.seconds - duration_seconds(line_stops)
            observed_mean_cycle = run_time_seconds / cycles
            expected_mean_cycle = CYCLE_TIME_MEAN_MULTIPLIER * float(line.ideal_cycle_time_seconds)
            _check_relative_band(
                findings,
                f"mean_cycle_time_out_of_band_line_{line.line_id}",
                observed_mean_cycle,
                expected_mean_cycle,
                ACCEPTANCE_BAND_CYCLE_TIME_RELATIVE,
            )

    for line_id, oee_value in oee_by_line.items():
        if oee_value is None:
            findings.append(
                Finding("statistical", "oee_null", f"line {line_id}: GET /oee returned oee=null")
            )
            continue
        oee_float = float(oee_value)
        if not (ACCEPTANCE_BAND_OEE_MIN <= oee_float <= ACCEPTANCE_BAND_OEE_MAX):
            findings.append(
                Finding(
                    "statistical",
                    "oee_out_of_band",
                    f"line {line_id}: oee={oee_float:.4f} not in "
                    f"[{ACCEPTANCE_BAND_OEE_MIN}, {ACCEPTANCE_BAND_OEE_MAX}]",
                )
            )

    return findings
