"""Topology/reason resolution against a real, migrated DB (real network and
generate()/transport() wiring are covered elsewhere -- see
tests/unit/test_simulator_generator.py and
tests/integration/test_simulator_client_roundtrip.py).
"""

import scripts.seed_demo as seed_demo
from scripts.simulate_production import (
    _REQUIRED_REASON_CODES,
    LINE_CODES,
    MACHINE_CODES_PER_LINE,
    _ensure_reason_catalog,
    _resolve_reason_ids,
    _resolve_topology,
)
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from paro.db.models import DowntimeReason, Machine, ProductionLine


def test_resolve_topology_creates_two_lines_of_four_machines(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        lines, machines = _resolve_topology(session)

    assert len(lines) == len(LINE_CODES)
    assert len(machines) == len(LINE_CODES) * len(MACHINE_CODES_PER_LINE)
    assert len({line.line_id for line in lines}) == len(LINE_CODES)
    assert len({machine.machine_id for machine in machines}) == len(machines)


def test_resolve_topology_is_idempotent(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        first_lines, first_machines = _resolve_topology(session)
    with Session(migrated_engine) as session:
        second_lines, second_machines = _resolve_topology(session)

    assert first_lines == second_lines
    assert first_machines == second_machines

    with Session(migrated_engine) as session:
        line_count = session.scalar(
            select(func.count())
            .select_from(ProductionLine)
            .where(ProductionLine.code.in_(LINE_CODES))
        )
        machine_count = session.scalar(select(func.count()).select_from(Machine))

    assert line_count == len(LINE_CODES)
    assert machine_count == len(LINE_CODES) * len(MACHINE_CODES_PER_LINE)


def test_resolve_reason_ids_finds_every_required_code_after_seed_demo(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        seed_demo.run(session)
        reason_ids = _resolve_reason_ids(session)

    assert set(reason_ids) == set(_REQUIRED_REASON_CODES)
    assert all(isinstance(reason_id, int) for reason_id in reason_ids.values())


def test_resolve_reason_ids_returns_partial_mapping_when_catalog_missing(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        reason_ids = _resolve_reason_ids(session)

    assert reason_ids == {}


def test_ensure_reason_catalog_populates_an_empty_catalog(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        reason_ids = _ensure_reason_catalog(session)

    assert set(reason_ids) == set(_REQUIRED_REASON_CODES)
    assert all(isinstance(reason_id, int) for reason_id in reason_ids.values())


def test_ensure_reason_catalog_seeds_only_missing_rows_and_is_idempotent(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        existing = DowntimeReason(
            code="FLA-M",
            name="Existing production label",
            default_is_planned=False,
        )
        session.add(existing)
        session.commit()
        existing_id = existing.id

        first = _ensure_reason_catalog(session)
        second = _ensure_reason_catalog(session)

        rows = session.execute(
            select(
                DowntimeReason.id,
                DowntimeReason.code,
                DowntimeReason.name,
                DowntimeReason.default_is_planned,
            ).where(DowntimeReason.code.in_(_REQUIRED_REASON_CODES))
        ).all()

    assert first == second
    assert set(first) == set(_REQUIRED_REASON_CODES)
    assert len(rows) == len(_REQUIRED_REASON_CODES)
    assert first["FLA-M"] == existing_id
    assert next(row.name for row in rows if row.code == "FLA-M") == "Existing production label"
    assert next(row.default_is_planned for row in rows if row.code == "CHG-P") is True
