"""``transport()``'s concurrent orchestration against a scripted fake
client -- no real network, no real database, so no SQLite
concurrent-write concerns (kept out of the real-DB path deliberately;
see tests/integration/test_simulator_client_roundtrip.py for that).
"""

import threading
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx2
import pytest
import scripts.simulator.client as simulator_client
from scripts.simulator.model import (
    DowntimeEventDraft,
    GeneratedRun,
    ProductionRecordDraft,
)
from scripts.simulator.transport import transport


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def json(self) -> Any:
        return {"status": self.status_code}


class _KeyedClient:
    """Responds by ``external_id`` in the request body, not call order --
    concurrent submission/completion order under a real thread pool isn't
    guaranteed to match scripting order."""

    def __init__(self, status_by_external_id: dict[str, int]) -> None:
        self._status_by_external_id = status_by_external_id
        self._lock = threading.Lock()
        self.calls: list[str] = []

    def request(
        self, method: str, url: str, *, json: Any = None, headers: Any = None
    ) -> _FakeResponse:
        external_id = json["external_id"]
        with self._lock:
            self.calls.append(external_id)
        return _FakeResponse(self._status_by_external_id[external_id])


def _production_record(external_id: str) -> ProductionRecordDraft:
    return ProductionRecordDraft(
        line_id=1,
        interval_start=datetime(2026, 8, 10, 6, 0, tzinfo=UTC),
        interval_end=datetime(2026, 8, 10, 6, 15, tzinfo=UTC),
        total_count=10,
        good_count=9,
        ideal_cycle_time_seconds=Decimal("30.000"),
        source="simulator",
        external_id=external_id,
    )


def _downtime_event(external_id: str) -> DowntimeEventDraft:
    return DowntimeEventDraft(
        line_id=1,
        machine_id=1,
        started_at=datetime(2026, 8, 10, 6, 0, tzinfo=UTC),
        ended_at=datetime(2026, 8, 10, 6, 1, tzinfo=UTC),
        reason_id=1,
        is_planned=False,
        operator_note=None,
        source="simulator",
        external_id=external_id,
    )


def test_mixed_batch_aggregates_counts_and_isolates_one_failure() -> None:
    pr_created = _production_record("pr-created")
    pr_existing = _production_record("pr-existing")
    pr_failed = _production_record("pr-failed")
    de_created = _downtime_event("de-created")
    de_existing = _downtime_event("de-existing")

    client = _KeyedClient(
        {
            "pr-created": 201,
            "pr-existing": 200,
            "pr-failed": 409,
            "de-created": 201,
            "de-existing": 200,
        }
    )
    run = GeneratedRun(
        production_records=(pr_created, pr_existing, pr_failed),
        downtime_events=(de_created, de_existing),
    )

    result = transport(run, base_url="http://api", client=client)

    assert result.production_records_created == 1
    assert result.production_records_existing == 1
    assert result.downtime_events_created == 1
    assert result.downtime_events_existing == 1
    assert result.succeeded is False
    assert len(result.failures) == 1
    assert result.failures[0].kind == "production_record"
    assert result.failures[0].draft == pr_failed
    assert "409" in result.failures[0].error
    # every row was actually attempted, despite one failure
    assert sorted(client.calls) == [
        "de-created",
        "de-existing",
        "pr-created",
        "pr-existing",
        "pr-failed",
    ]


def test_all_success_reports_no_failures() -> None:
    pr = _production_record("pr-1")
    de = _downtime_event("de-1")
    client = _KeyedClient({"pr-1": 201, "de-1": 200})
    run = GeneratedRun(production_records=(pr,), downtime_events=(de,))

    result = transport(run, base_url="http://api", client=client)

    assert result.succeeded is True
    assert result.failures == ()


def test_empty_run_produces_zero_counts() -> None:
    run = GeneratedRun(production_records=(), downtime_events=())
    client = _KeyedClient({})

    result = transport(run, base_url="http://api", client=client)

    assert result.succeeded is True
    assert result.production_records_created == 0
    assert result.downtime_events_created == 0


def test_timeout_is_collected_without_aborting_other_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successful = _production_record("pr-success")
    timed_out = _production_record("pr-timeout")

    class TimeoutClient(_KeyedClient):
        def request(
            self, method: str, url: str, *, json: Any = None, headers: Any = None
        ) -> _FakeResponse:
            if json["external_id"] == "pr-timeout":
                raise httpx2.TimeoutException("simulated timeout")
            return super().request(method, url, json=json, headers=headers)

    monkeypatch.setattr(simulator_client, "RETRY_MAX_ATTEMPTS", 1)
    result = transport(
        GeneratedRun(production_records=(successful, timed_out), downtime_events=()),
        base_url="http://api",
        client=TimeoutClient({"pr-success": 201}),
    )

    assert result.production_records_created == 1
    assert len(result.failures) == 1
    assert result.failures[0].draft == timed_out
    assert "TimeoutException" in result.failures[0].error
