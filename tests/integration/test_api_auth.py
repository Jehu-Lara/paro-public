"""Real end-to-end check of docs/adr/0005-optional-api-key-authentication.md
against the actual FastAPI app: missing/wrong X-API-Key -> 401 on all
three write endpoints when PARO_API_KEY is configured, correct header ->
normal success, and reads stay open regardless.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from paro.api.auth import API_KEY_HEADER
from paro.config import get_settings
from paro.db.models import DowntimeEvent, DowntimeReason, ProductionLine

STARTED_AT = datetime(2026, 8, 10, 22, 0, tzinfo=UTC).isoformat()
ENDED_AT = datetime(2026, 8, 10, 22, 5, tzinfo=UTC).isoformat()


@pytest.fixture(autouse=True)
def _api_key_configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PARO_API_KEY", "secret-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _seed_line_and_reason(migrated_engine: Engine) -> tuple[int, int]:
    with Session(migrated_engine) as session:
        line = ProductionLine(code="L1", name="Linea 1", timezone="America/Monterrey", active=True)
        reason = DowntimeReason(code="R1", name="Falla mecanica", default_is_planned=False)
        session.add_all([line, reason])
        session.commit()
        return line.id, reason.id


def test_post_downtime_event_401_without_key(client: TestClient, migrated_engine: Engine) -> None:
    line_id, reason_id = _seed_line_and_reason(migrated_engine)

    response = client.post(
        "/api/v1/downtime-events",
        json={
            "line_id": line_id,
            "reason_id": reason_id,
            "started_at": STARTED_AT,
            "ended_at": ENDED_AT,
            "is_planned": False,
            "source": "mes",
            "external_id": "evt-1",
        },
    )

    assert response.status_code == 401


def test_post_downtime_event_401_with_wrong_key(
    client: TestClient, migrated_engine: Engine
) -> None:
    line_id, reason_id = _seed_line_and_reason(migrated_engine)

    response = client.post(
        "/api/v1/downtime-events",
        json={
            "line_id": line_id,
            "reason_id": reason_id,
            "started_at": STARTED_AT,
            "ended_at": ENDED_AT,
            "is_planned": False,
            "source": "mes",
            "external_id": "evt-1",
        },
        headers={API_KEY_HEADER: "wrong-key"},
    )

    assert response.status_code == 401


def test_post_downtime_event_201_with_correct_key(
    client: TestClient, migrated_engine: Engine
) -> None:
    line_id, reason_id = _seed_line_and_reason(migrated_engine)

    response = client.post(
        "/api/v1/downtime-events",
        json={
            "line_id": line_id,
            "reason_id": reason_id,
            "started_at": STARTED_AT,
            "ended_at": ENDED_AT,
            "is_planned": False,
            "source": "mes",
            "external_id": "evt-1",
        },
        headers={API_KEY_HEADER: "secret-key"},
    )

    assert response.status_code == 201


def test_post_production_record_401_without_key(
    client: TestClient, migrated_engine: Engine
) -> None:
    line_id, _ = _seed_line_and_reason(migrated_engine)

    response = client.post(
        "/api/v1/production-records",
        json={
            "line_id": line_id,
            "interval_start": STARTED_AT,
            "interval_end": ENDED_AT,
            "total_count": 100,
            "good_count": 95,
            "ideal_cycle_time_seconds": "12.5",
            "source": "mes",
            "external_id": "rec-1",
        },
    )

    assert response.status_code == 401


def test_post_production_record_201_with_correct_key(
    client: TestClient, migrated_engine: Engine
) -> None:
    line_id, _ = _seed_line_and_reason(migrated_engine)

    response = client.post(
        "/api/v1/production-records",
        json={
            "line_id": line_id,
            "interval_start": STARTED_AT,
            "interval_end": ENDED_AT,
            "total_count": 100,
            "good_count": 95,
            "ideal_cycle_time_seconds": "12.5",
            "source": "mes",
            "external_id": "rec-1",
        },
        headers={API_KEY_HEADER: "secret-key"},
    )

    assert response.status_code == 201


def _seed_event(migrated_engine: Engine) -> tuple[int, str]:
    with Session(migrated_engine) as session:
        line = ProductionLine(code="L1", name="Linea 1", timezone="America/Monterrey", active=True)
        reason = DowntimeReason(code="R1", name="Falla mecanica", default_is_planned=False)
        session.add_all([line, reason])
        session.flush()
        event = DowntimeEvent(
            line_id=line.id,
            started_at=datetime.fromisoformat(STARTED_AT),
            ended_at=datetime.fromisoformat(ENDED_AT),
            reason_id=reason.id,
            is_planned=False,
        )
        session.add(event)
        session.commit()
        return event.id, event.updated_at.isoformat()


def test_patch_downtime_event_401_without_key(client: TestClient, migrated_engine: Engine) -> None:
    event_id, expected_updated_at = _seed_event(migrated_engine)

    response = client.patch(
        f"/api/v1/downtime-events/{event_id}",
        json={
            "expected_updated_at": expected_updated_at,
            "operator_note": "corrected",
            "actor": "supervisor@example.com",
        },
    )

    assert response.status_code == 401


def test_patch_downtime_event_200_with_correct_key(
    client: TestClient, migrated_engine: Engine
) -> None:
    event_id, expected_updated_at = _seed_event(migrated_engine)

    response = client.patch(
        f"/api/v1/downtime-events/{event_id}",
        json={
            "expected_updated_at": expected_updated_at,
            "operator_note": "corrected",
            "actor": "supervisor@example.com",
        },
        headers={API_KEY_HEADER: "secret-key"},
    )

    assert response.status_code == 200


def test_oee_read_stays_open_regardless_of_configured_key(
    client: TestClient, migrated_engine: Engine
) -> None:
    line_id, _ = _seed_line_and_reason(migrated_engine)

    response = client.get(
        "/api/v1/oee",
        params={"line_id": line_id, "start": STARTED_AT, "end": ENDED_AT},
    )

    assert response.status_code == 200
