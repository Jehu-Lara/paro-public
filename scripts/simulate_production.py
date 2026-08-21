"""CLI entrypoint wiring the simulator's core generator to real transport
(docs/adr/0004-simulator-multi-agent-architecture.md,
docs/simulator-spec.md).

Precondition this script cannot verify programmatically -- an operator
responsibility: the database ``paro.db.session.get_session_local()``
resolves (from local env config) and the API server answering at
``--base-url`` must be **the same database**. Topology/reason resolution
uses the local DB session directly (no GET endpoints exist for
ProductionLine/Machine/DowntimeReason); every actual write goes through
``--base-url`` over HTTP. These two are resolved completely
independently -- if they diverge, this script silently seeds a
topology/reason set the target API's database can't see, and every
``transport()`` write then fails with an opaque 404/422 that gives no
hint the real cause is a DB/API mismatch, not a data bug. The startup
summary prints the resolved DB identity next to ``--base-url`` so a
mismatch is visible immediately, not just as a wall of unexplained
transport failures.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from paro.db.models import DowntimeReason, Machine, ProductionLine
from paro.db.session import get_engine, get_session_local
from scripts.simulator.client import API_KEY_ENV_VAR, TRUSTED_INGEST_TOKEN_ENV_VAR
from scripts.simulator.config import (
    MASTER_SEED,
    REASON_CODES_BY_FAILURE_CLASS,
    REASON_CODES_BY_MICRO_STOP_CLASS,
    REASON_PLANNED_CHANGEOVER_CODE,
)
from scripts.simulator.generator import generate
from scripts.simulator.model import LineConfig, MachineConfig, SimulatorConfig
from scripts.simulator.transport import DEFAULT_MAX_WORKERS, transport

__all__ = ["main"]

LINE_CODES = ("SIM-L1", "SIM-L2")
MACHINE_CODES_PER_LINE = ("M1", "M2", "M3", "M4")
DEFAULT_IDEAL_CYCLE_TIME_SECONDS = Decimal("30.000")

_REQUIRED_REASON_CODES = frozenset(
    {REASON_PLANNED_CHANGEOVER_CODE}
    | set(REASON_CODES_BY_FAILURE_CLASS.values())
    | set(REASON_CODES_BY_MICRO_STOP_CLASS.values())
)


def _get_or_create_line(session: Session, code: str) -> ProductionLine:
    existing = session.execute(
        select(ProductionLine).where(ProductionLine.code == code)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    line = ProductionLine(code=code, name=code, timezone="America/Monterrey", active=True)
    session.add(line)
    session.flush()
    return line


def _get_or_create_machine(session: Session, line: ProductionLine, code: str) -> Machine:
    existing = session.execute(
        select(Machine).where(Machine.line_id == line.id, Machine.code == code)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    machine = Machine(line_id=line.id, code=code, name=f"{line.code} {code}")
    session.add(machine)
    session.flush()
    return machine


def _resolve_topology(session: Session) -> tuple[tuple[LineConfig, ...], tuple[MachineConfig, ...]]:
    """Get-or-creates the dedicated SIM-* topology (simulator-spec.md 4.5):
    2 lines x 4 machines, isolated from scripts/seed_demo.py's own L1/M1/M2.
    """
    lines: list[LineConfig] = []
    machines: list[MachineConfig] = []
    for line_code in LINE_CODES:
        line = _get_or_create_line(session, line_code)
        lines.append(
            LineConfig(
                line_id=line.id,
                ideal_cycle_time_seconds=DEFAULT_IDEAL_CYCLE_TIME_SECONDS,
            )
        )
        for machine_code in MACHINE_CODES_PER_LINE:
            machine = _get_or_create_machine(session, line, machine_code)
            machines.append(MachineConfig(machine_id=machine.id, line_id=line.id))
    session.commit()
    return tuple(lines), tuple(machines)


def _resolve_reason_ids(session: Session) -> dict[str, int]:
    """Queries existing downtime_reason rows by code -- does not seed them.

    scripts/seed_demo.py already seeds the full catalog (simulator-spec.md
    4.6). If a required code is missing here, generate()'s own _validate()
    raises a clear ValueError; this function doesn't duplicate that check.
    """
    rows = session.execute(
        select(DowntimeReason.code, DowntimeReason.id).where(
            DowntimeReason.code.in_(_REQUIRED_REASON_CODES)
        )
    ).all()
    return {code: reason_id for code, reason_id in rows}


def _parse_tz_aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(
            f"{value!r} has no timezone offset -- generate() requires tz-aware start/end"
        )
    return parsed


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=_parse_tz_aware_datetime, required=True)
    parser.add_argument("--end", type=_parse_tz_aware_datetime, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--seed", type=int, default=MASTER_SEED)
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    return parser.parse_args(argv)


def _database_identity() -> str:
    """Host + database name only -- never credentials."""
    url = get_engine().url
    return f"{url.drivername}://{url.host or ''}/{url.database or ''}"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    print(f"[simulate_production] DB: {_database_identity()}  API: {args.base_url}")

    with get_session_local()() as session:
        lines, machines = _resolve_topology(session)
        reason_ids = _resolve_reason_ids(session)

    config = SimulatorConfig(lines=lines, machines=machines, reason_ids=reason_ids)
    run = generate(config, args.seed, args.start, args.end)
    print(
        f"[simulate_production] Generated: {len(run.production_records)} production_records, "
        f"{len(run.downtime_events)} downtime_events"
    )

    result = transport(
        run,
        base_url=args.base_url,
        max_workers=args.max_workers,
        api_key=os.environ.get(API_KEY_ENV_VAR),
        trusted_ingest_token=os.environ.get(TRUSTED_INGEST_TOKEN_ENV_VAR),
    )
    print(
        f"[simulate_production] Transport: "
        f"production_records created={result.production_records_created} "
        f"existing={result.production_records_existing}, "
        f"downtime_events created={result.downtime_events_created} "
        f"existing={result.downtime_events_existing}"
    )
    if result.failures:
        print(f"[simulate_production] {len(result.failures)} failure(s):")
        for failure in result.failures:
            print(f"  - {failure.kind} {failure.draft.external_id}: {failure.error}")

    return 0 if result.succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
