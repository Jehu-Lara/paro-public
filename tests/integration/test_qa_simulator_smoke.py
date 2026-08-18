"""SMOKE-shaped pipeline wiring against a real migrated DB + TestClient
(same fixture pattern as tests/integration/test_simulator_client_roundtrip.py).

Deliberately NOT the spec's actual 1-day/2-machine SMOKE scale: a real
run at that volume (96 production_records + ~188 downtime_events, doubled
for idempotency) took 17 minutes against a real TestClient/SQLite DB when
first tried here -- SQLite's per-commit overhead, not a hang. This test's
job is proving the generate() -> check_structural -> transport() ->
transport() -> check_idempotency wiring is correct against a real DB, not
reproducing SMOKE-tier volume (that's what a real `qa_simulator.py
--tier smoke` run against a live server does, deliberately out of scope
for the automated suite -- see the implementation plan). A one-hour
window (4 production_record buckets, 1 machine) exercises the same code
path in seconds. Not the ACCEPTANCE tier either -- that's a live-server
manual run, also out of scope here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import scripts.seed_demo as seed_demo
from fastapi.testclient import TestClient
from scripts.qa_simulator import _reason_planned_by_id, _run_and_check
from scripts.simulate_production import _resolve_reason_ids, _resolve_topology
from scripts.simulator.config import MASTER_SEED
from scripts.simulator.generator import generate
from scripts.simulator.model import SimulatorConfig
from scripts.simulator.qa import check_structural
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from paro.db.models import DowntimeReason

_START = datetime(2026, 8, 10, 6, 0, tzinfo=UTC)
_END = _START + timedelta(hours=1)


def _seed_topology_and_catalog(session: Session) -> SimulatorConfig:
    seed_demo.run(session)
    lines, machines = _resolve_topology(session)
    reason_ids = _resolve_reason_ids(session)
    return SimulatorConfig(lines=lines, machines=machines, reason_ids=reason_ids)


def _one_machine_config(config: SimulatorConfig) -> SimulatorConfig:
    line = config.lines[0]
    machine = min(
        (m for m in config.machines if m.line_id == line.line_id), key=lambda m: m.machine_id
    )
    return SimulatorConfig(lines=(line,), machines=(machine,), reason_ids=config.reason_ids)


def test_smoke_shaped_run_and_idempotency_pass_with_zero_findings(
    client: TestClient, migrated_engine: Engine
) -> None:
    with Session(migrated_engine) as session:
        full_config = _seed_topology_and_catalog(session)
        reason_planned_by_id = _reason_planned_by_id(session)

    small_config = _one_machine_config(full_config)

    findings, _ = _run_and_check(
        client,
        small_config,
        MASTER_SEED,
        _START,
        _END,
        "",
        reason_planned_by_id,
        1,  # max_workers=1: SQLite doesn't handle concurrent writes (ADR 0002/0003), same
        # constraint test_simulator_client_roundtrip.py's own docstring already flags
        None,
    )

    assert findings == []


def test_corrupted_catalog_produces_is_planned_mismatch_finding(
    client: TestClient, migrated_engine: Engine
) -> None:
    with Session(migrated_engine) as session:
        full_config = _seed_topology_and_catalog(session)

        mechanical_reason = session.execute(
            select(DowntimeReason).where(DowntimeReason.code == "FLA-M")
        ).scalar_one()
        mechanical_reason.default_is_planned = True
        session.commit()

        reason_planned_by_id = _reason_planned_by_id(session)

    small_config = _one_machine_config(full_config)
    # A full simulated day (not the 1-hour window above) to reliably draw at
    # least one mechanical-reason failure event -- generation is pure/fast,
    # no transport involved here, so the larger window costs nothing.
    end = _START + timedelta(days=1)
    run = generate(small_config, MASTER_SEED, _START, end)

    findings = check_structural(run, small_config, _START, end, reason_planned_by_id)

    mismatches = [f for f in findings if f.check == "is_planned_mismatch"]
    assert mismatches
    assert "is_planned=False" in mismatches[0].detail
    assert "default_is_planned=True" in mismatches[0].detail
    assert all(f.check == "is_planned_mismatch" for f in findings)
