"""``POST /api/v1/downtime-events``: idempotencia HTTP real (201/200/409) y
FKs invalidas (404), verificadas por el codigo de estado real, no solo el
body.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from paro.db.models import DowntimeEvent, DowntimeReason, ProductionLine

NOW = datetime(2026, 8, 10, 22, 0, tzinfo=UTC).isoformat()
LATER = datetime(2026, 8, 10, 22, 5, tzinfo=UTC).isoformat()
EVEN_LATER = datetime(2026, 8, 10, 22, 45, tzinfo=UTC).isoformat()


def _seed_line_and_reason(migrated_engine: Engine) -> tuple[int, int]:
    with Session(migrated_engine) as session:
        line = ProductionLine(code="L1", name="Linea 1", timezone="America/Monterrey", active=True)
        reason = DowntimeReason(code="R1", name="Falla mecanica", default_is_planned=False)
        session.add_all([line, reason])
        session.commit()
        return line.id, reason.id


def _payload(line_id: int, reason_id: int, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "line_id": line_id,
        "reason_id": reason_id,
        "started_at": NOW,
        "ended_at": LATER,
        "is_planned": False,
        "source": "mes",
        "external_id": "evt-1",
    }
    base.update(overrides)
    return base


def test_post_new_event_returns_201(client: TestClient, migrated_engine: Engine) -> None:
    line_id, reason_id = _seed_line_and_reason(migrated_engine)

    response = client.post("/api/v1/downtime-events", json=_payload(line_id, reason_id))

    assert response.status_code == 201
    body = response.json()
    assert body["line_id"] == line_id
    assert body["reason_id"] == reason_id
    assert body["id"] is not None

    with Session(migrated_engine) as session:
        count = session.scalar(select(func.count()).select_from(DowntimeEvent))
        assert count == 1


def test_post_same_payload_returns_200_no_duplicate(
    client: TestClient, migrated_engine: Engine
) -> None:
    line_id, reason_id = _seed_line_and_reason(migrated_engine)
    payload = _payload(line_id, reason_id)

    first = client.post("/api/v1/downtime-events", json=payload)
    second = client.post("/api/v1/downtime-events", json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]

    with Session(migrated_engine) as session:
        count = session.scalar(select(func.count()).select_from(DowntimeEvent))
        assert count == 1


def test_post_different_payload_same_key_returns_409(
    client: TestClient, migrated_engine: Engine
) -> None:
    line_id, reason_id = _seed_line_and_reason(migrated_engine)
    client.post("/api/v1/downtime-events", json=_payload(line_id, reason_id))

    response = client.post(
        "/api/v1/downtime-events", json=_payload(line_id, reason_id, ended_at=EVEN_LATER)
    )

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "duplicate_with_different_payload"
    assert body["source"] == "mes"
    assert body["external_id"] == "evt-1"
    assert "ended_at" in body["differing_fields"]

    with Session(migrated_engine) as session:
        count = session.scalar(select(func.count()).select_from(DowntimeEvent))
        assert count == 1


def test_post_unknown_line_returns_404(client: TestClient, migrated_engine: Engine) -> None:
    _, reason_id = _seed_line_and_reason(migrated_engine)

    response = client.post("/api/v1/downtime-events", json=_payload(999, reason_id))

    assert response.status_code == 404


def test_post_unknown_reason_returns_404(client: TestClient, migrated_engine: Engine) -> None:
    line_id, _ = _seed_line_and_reason(migrated_engine)

    response = client.post("/api/v1/downtime-events", json=_payload(line_id, 999))

    assert response.status_code == 404


def test_post_unknown_machine_returns_404(client: TestClient, migrated_engine: Engine) -> None:
    line_id, reason_id = _seed_line_and_reason(migrated_engine)

    response = client.post(
        "/api/v1/downtime-events", json=_payload(line_id, reason_id, machine_id=999)
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"started_at": "2026-08-10T22:00:00"},  # naive
        {"ended_at": "2026-08-10T21:00:00Z"},  # ended_at <= started_at
    ],
)
def test_post_invalid_payload_returns_422(
    client: TestClient, migrated_engine: Engine, overrides: dict[str, object]
) -> None:
    line_id, reason_id = _seed_line_and_reason(migrated_engine)

    response = client.post(
        "/api/v1/downtime-events", json=_payload(line_id, reason_id, **overrides)
    )

    assert response.status_code == 422
