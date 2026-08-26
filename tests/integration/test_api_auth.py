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
from paro.api.rate_limit import TRUSTED_INGEST_HEADER, limiter
from paro.config import get_settings
from paro.db.models import DowntimeEvent, DowntimeReason, ProductionLine

STARTED_AT = datetime(2026, 8, 10, 22, 0, tzinfo=UTC).isoformat()
ENDED_AT = datetime(2026, 8, 10, 22, 5, tzinfo=UTC).isoformat()


@pytest.fixture(autouse=True)
def _api_key_configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PARO_ENV", "production")
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


def test_trusted_ingest_token_alone_never_authenticates(
    client: TestClient, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    line_id, _ = _seed_line_and_reason(migrated_engine)
    monkeypatch.setenv("PARO_TRUSTED_INGEST_TOKEN", "ingest-secret")
    get_settings.cache_clear()
    response = client.post(
        "/api/v1/production-records",
        headers={TRUSTED_INGEST_HEADER: "ingest-secret"},
        json={
            "line_id": line_id,
            "interval_start": STARTED_AT,
            "interval_end": ENDED_AT,
            "total_count": 10,
            "good_count": 9,
            "ideal_cycle_time_seconds": "12.5",
            "source": "cross-auth",
            "external_id": "trusted-only",
        },
    )
    assert response.status_code == 401


def test_api_key_without_trusted_token_remains_rate_limited(
    client: TestClient, migrated_engine: Engine
) -> None:
    line_id, _ = _seed_line_and_reason(migrated_engine)
    limiter.reset()
    statuses = []
    for index in range(31):
        response = client.post(
            "/api/v1/production-records",
            headers={API_KEY_HEADER: "secret-key"},
            json={
                "line_id": line_id,
                "interval_start": STARTED_AT,
                "interval_end": ENDED_AT,
                "total_count": 10,
                "good_count": 9,
                "ideal_cycle_time_seconds": "12.5",
                "source": "cross-auth-limited",
                "external_id": f"limited-{index}",
            },
        )
        statuses.append(response.status_code)
    assert statuses[:30] == [201] * 30
    assert statuses[30] == 429


def test_both_credentials_authorize_and_exempt_rate_limit(
    client: TestClient,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    line_id, _ = _seed_line_and_reason(migrated_engine)
    monkeypatch.setenv("PARO_TRUSTED_INGEST_TOKEN", "ingest-secret")
    get_settings.cache_clear()
    limiter.reset()
    statuses = []
    for index in range(31):
        response = client.post(
            "/api/v1/production-records",
            headers={
                API_KEY_HEADER: "secret-key",
                TRUSTED_INGEST_HEADER: "ingest-secret",
            },
            json={
                "line_id": line_id,
                "interval_start": STARTED_AT,
                "interval_end": ENDED_AT,
                "total_count": 10,
                "good_count": 9,
                "ideal_cycle_time_seconds": "12.5",
                "source": "cross-auth-exempt",
                "external_id": f"exempt-{index}",
            },
        )
        statuses.append(response.status_code)
    assert statuses == [201] * 31


def test_credentials_never_appear_in_request_logs(
    client: TestClient,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    line_id, _ = _seed_line_and_reason(migrated_engine)
    monkeypatch.setenv("PARO_TRUSTED_INGEST_TOKEN", "ingest-secret")
    get_settings.cache_clear()
    limiter.reset()
    client.post(
        "/api/v1/production-records",
        headers={API_KEY_HEADER: "secret-key", TRUSTED_INGEST_HEADER: "ingest-secret"},
        json={
            "line_id": line_id,
            "interval_start": STARTED_AT,
            "interval_end": ENDED_AT,
            "total_count": 10,
            "good_count": 9,
            "ideal_cycle_time_seconds": "12.5",
            "source": "cross-auth-log",
            "external_id": "log-check",
        },
    )
    assert "secret-key" not in caplog.text
    assert "ingest-secret" not in caplog.text
