"""Real round-trip: scripts/simulator/client.py's functions, unmodified,
through the actual FastAPI app + real DB (via the existing
tests/integration/conftest.py fixtures).

Proves the dataclasses.asdict(draft) + json_safe(...) serialization
(Decimal, tz-aware datetimes) actually satisfies the real Pydantic
validators end-to-end -- not just a shape assumption. Single-threaded, no
concurrency exercised here: kept out of the real-DB path deliberately, to
avoid SQLite concurrent-write flakiness (ADR 0002/0003 already flag
SQLite's concurrency limits as a known constraint of this environment).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from scripts.simulator.client import post_downtime_event, post_production_record
from scripts.simulator.model import DowntimeEventDraft, ProductionRecordDraft
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from paro.db.models import DowntimeEvent, DowntimeReason, ProductionLine, ProductionRecord


def _seed_line_and_reason(migrated_engine: Engine) -> tuple[int, int]:
    with Session(migrated_engine) as session:
        line = ProductionLine(code="L1", name="Linea 1", timezone="America/Monterrey", active=True)
        reason = DowntimeReason(code="FLA-M", name="Falla mecanica", default_is_planned=False)
        session.add_all([line, reason])
        session.commit()
        return line.id, reason.id


def test_production_record_round_trip(client: TestClient, migrated_engine: Engine) -> None:
    line_id, _ = _seed_line_and_reason(migrated_engine)
    draft = ProductionRecordDraft(
        line_id=line_id,
        interval_start=datetime(2026, 8, 10, 6, 0, tzinfo=UTC),
        interval_end=datetime(2026, 8, 10, 6, 15, tzinfo=UTC),
        total_count=10,
        good_count=9,
        ideal_cycle_time_seconds=Decimal("30.000"),
        source="simulator",
        external_id="sim-line-roundtrip-1",
    )

    body, was_created = post_production_record(client, "", draft)

    assert was_created is True
    assert body["line_id"] == line_id
    assert body["total_count"] == 10
    assert body["good_count"] == 9

    with Session(migrated_engine) as session:
        row = session.get(ProductionRecord, body["id"])
        assert row is not None
        assert row.ideal_cycle_time_seconds == Decimal("30.000")

    # Re-posting the identical draft is an idempotent no-op (200, not 201).
    _, was_created_again = post_production_record(client, "", draft)
    assert was_created_again is False


def test_downtime_event_round_trip(client: TestClient, migrated_engine: Engine) -> None:
    line_id, reason_id = _seed_line_and_reason(migrated_engine)
    draft = DowntimeEventDraft(
        line_id=line_id,
        machine_id=None,
        started_at=datetime(2026, 8, 10, 6, 0, tzinfo=UTC),
        ended_at=datetime(2026, 8, 10, 6, 1, tzinfo=UTC),
        reason_id=reason_id,
        is_planned=False,
        operator_note=None,
        source="simulator",
        external_id="sim-machine1-roundtrip-1",
    )

    body, was_created = post_downtime_event(client, "", draft)

    assert was_created is True
    assert body["line_id"] == line_id
    assert body["reason_id"] == reason_id
    assert body["is_planned"] is False

    with Session(migrated_engine) as session:
        row = session.get(DowntimeEvent, body["id"])
        assert row is not None
        assert row.started_at == draft.started_at

    _, was_created_again = post_downtime_event(client, "", draft)
    assert was_created_again is False
