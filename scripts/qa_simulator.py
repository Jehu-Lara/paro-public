"""QA Agent runner (docs/simulator-spec.md sections 7-9;
docs/adr/0004-simulator-multi-agent-architecture.md's 2026-08-18
revision). No LangGraph, no Ollama, no autonomous Developer Agent -- see
that revision for why. Reuses simulate_production.py's topology/reason
resolution and generate()/transport() pipeline unmodified; only adds
structural/idempotency/statistical checks on top and reports structured
findings.

Same DB/API same-database precondition as scripts/simulate_production.py
applies here unchanged -- see that module's docstring.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx2
from sqlalchemy import select
from sqlalchemy.orm import Session

from paro.db.models import DowntimeReason
from paro.db.session import get_session_local
from scripts.simulate_production import (
    _database_identity,
    _resolve_reason_ids,
    _resolve_topology,
)
from scripts.simulator.client import (
    REQUEST_TIMEOUT_SECONDS,
    HttpClient,
    load_api_credentials,
)
from scripts.simulator.config import (
    ACCEPTANCE_DURATION_DAYS,
    MASTER_SEED,
    SMOKE_DURATION_DAYS,
    SMOKE_MACHINE_COUNT,
)
from scripts.simulator.generator import generate
from scripts.simulator.model import GeneratedRun, SimulatorConfig
from scripts.simulator.qa import (
    Finding,
    check_idempotency,
    check_statistical_bands,
    check_structural,
)
from scripts.simulator.transport import DEFAULT_MAX_WORKERS, transport

__all__ = ["main"]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--seed", type=int, default=MASTER_SEED)
    parser.add_argument("--tier", choices=["smoke", "acceptance"], default="smoke")
    return parser.parse_args(argv)


def _reason_planned_by_id(session: Session) -> dict[int, bool]:
    rows = session.execute(select(DowntimeReason.id, DowntimeReason.default_is_planned)).all()
    return {reason_id: default_is_planned for reason_id, default_is_planned in rows}


def _smoke_config(config: SimulatorConfig) -> SimulatorConfig:
    line = config.lines[0]
    machines = sorted(
        (m for m in config.machines if m.line_id == line.line_id), key=lambda m: m.machine_id
    )[:SMOKE_MACHINE_COUNT]
    return SimulatorConfig(lines=(line,), machines=tuple(machines), reason_ids=config.reason_ids)


def _get_oee(
    client: HttpClient, base_url: str, line_id: int, start: datetime, end: datetime
) -> Any:
    query = urlencode({"line_id": line_id, "start": start.isoformat(), "end": end.isoformat()})
    response = client.request("GET", f"{base_url}/api/v1/oee?{query}")
    if response.status_code != 200:
        return None
    body = response.json()
    oee = body.get("oee")
    return Decimal(oee) if oee is not None else None


def _run_and_check(
    client: HttpClient,
    config: SimulatorConfig,
    seed: int,
    start: datetime,
    end: datetime,
    base_url: str,
    reason_planned_by_id: dict[int, bool],
    max_workers: int,
    api_key: str | None,
    trusted_ingest_token: str | None,
) -> tuple[list[Finding], GeneratedRun]:
    findings: list[Finding] = []

    run = generate(config, seed, start, end)
    findings.extend(check_structural(run, config, start, end, reason_planned_by_id))

    first_result = transport(
        run,
        base_url=base_url,
        max_workers=max_workers,
        api_key=api_key,
        trusted_ingest_token=trusted_ingest_token,
        client=client,
    )
    for failure in first_result.failures:
        findings.append(
            Finding(
                "structural",
                "schema_constraint_violation",
                f"{failure.kind} {failure.draft.external_id}: {failure.error}",
            )
        )

    second_result = transport(
        run,
        base_url=base_url,
        max_workers=max_workers,
        api_key=api_key,
        trusted_ingest_token=trusted_ingest_token,
        client=client,
    )
    findings.extend(check_idempotency(first_result, second_result))

    return findings, run


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    print(f"[qa_simulator] DB: {_database_identity()}  API: {args.base_url}  tier: {args.tier}")

    with get_session_local()() as session:
        lines, machines = _resolve_topology(session)
        reason_ids = _resolve_reason_ids(session)
        reason_planned_by_id = _reason_planned_by_id(session)

    full_config = SimulatorConfig(lines=lines, machines=machines, reason_ids=reason_ids)
    credentials = load_api_credentials()
    findings: list[Finding] = []

    with httpx2.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        smoke_config = _smoke_config(full_config)
        smoke_end = datetime.now(UTC)
        smoke_start = smoke_end - timedelta(days=SMOKE_DURATION_DAYS)
        smoke_findings, _ = _run_and_check(
            client,
            smoke_config,
            args.seed,
            smoke_start,
            smoke_end,
            args.base_url,
            reason_planned_by_id,
            DEFAULT_MAX_WORKERS,
            credentials.api_key,
            credentials.trusted_ingest_token,
        )
        findings.extend(smoke_findings)

        if args.tier == "acceptance":
            acceptance_end = datetime.now(UTC)
            acceptance_start = acceptance_end - timedelta(days=ACCEPTANCE_DURATION_DAYS)
            acceptance_findings, acceptance_run = _run_and_check(
                client,
                full_config,
                args.seed,
                acceptance_start,
                acceptance_end,
                args.base_url,
                reason_planned_by_id,
                DEFAULT_MAX_WORKERS,
                credentials.api_key,
                credentials.trusted_ingest_token,
            )
            findings.extend(acceptance_findings)
            oee_by_line = {
                line.line_id: _get_oee(
                    client, args.base_url, line.line_id, acceptance_start, acceptance_end
                )
                for line in full_config.lines
            }
            findings.extend(
                check_statistical_bands(
                    acceptance_run, full_config, ACCEPTANCE_DURATION_DAYS, oee_by_line
                )
            )

    if findings:
        print(f"[qa_simulator] {len(findings)} finding(s):")
        for finding in findings:
            print(f"  - [{finding.tier}] {finding.check}: {finding.detail}")
        return 1

    print("[qa_simulator] PASS: no findings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
