"""``POST /api/v1/production-records``: idempotencia HTTP real (201/200/409),
FK invalida (404) y ``rejected_count`` derivado en la respuesta.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from paro.db.models import ProductionLine, ProductionRecord

START = datetime(2026, 8, 10, 22, 0, tzinfo=UTC).isoformat()
END = datetime(2026, 8, 10, 23, 0, tzinfo=UTC).isoformat()


def _seed_line(migrated_engine: Engine) -> int:
    with Session(migrated_engine) as session:
        line = ProductionLine(code="L1", name="Linea 1", timezone="America/Monterrey", active=True)
        session.add(line)
        session.commit()
        return line.id


def _payload(line_id: int, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "line_id": line_id,
        "interval_start": START,
        "interval_end": END,
        "total_count": 100,
        "good_count": 95,
        "ideal_cycle_time_seconds": "12.5",
        "source": "mes",
        "external_id": "rec-1",
    }
    base.update(overrides)
    return base


def test_post_new_record_returns_201_with_rejected_count(
    client: TestClient, migrated_engine: Engine
) -> None:
    line_id = _seed_line(migrated_engine)

    response = client.post("/api/v1/production-records", json=_payload(line_id))

    assert response.status_code == 201
    body = response.json()
    assert body["total_count"] == 100
    assert body["good_count"] == 95
    assert body["rejected_count"] == 5
    assert body["ideal_cycle_time_seconds"] == "12.500"
    assert isinstance(body["ideal_cycle_time_seconds"], str)

    with Session(migrated_engine) as session:
        count = session.scalar(select(func.count()).select_from(ProductionRecord))
        assert count == 1


def test_post_same_payload_returns_200_no_duplicate(
    client: TestClient, migrated_engine: Engine
) -> None:
    line_id = _seed_line(migrated_engine)
    payload = _payload(line_id)

    first = client.post("/api/v1/production-records", json=payload)
    second = client.post("/api/v1/production-records", json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]

    with Session(migrated_engine) as session:
        count = session.scalar(select(func.count()).select_from(ProductionRecord))
        assert count == 1


def test_post_different_payload_same_key_returns_409(
    client: TestClient, migrated_engine: Engine
) -> None:
    line_id = _seed_line(migrated_engine)
    client.post("/api/v1/production-records", json=_payload(line_id))

    response = client.post("/api/v1/production-records", json=_payload(line_id, good_count=80))

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "duplicate_with_different_payload"
    assert "good_count" in body["differing_fields"]

    with Session(migrated_engine) as session:
        count = session.scalar(select(func.count()).select_from(ProductionRecord))
        assert count == 1


def test_post_excess_precision_ideal_cycle_time_returns_422(
    client: TestClient, migrated_engine: Engine
) -> None:
    """Regression: 4+ decimal places must be rejected at the API boundary,
    not silently truncated by the ``Numeric(precision=10, scale=3)`` column
    and then compared against the truncated value on a repeated POST (which
    previously produced a spurious 409 instead of the expected idempotent
    no-op).
    """
    line_id = _seed_line(migrated_engine)
    payload = _payload(line_id, ideal_cycle_time_seconds="12.5555")

    first = client.post("/api/v1/production-records", json=payload)
    second = client.post("/api/v1/production-records", json=payload)

    assert first.status_code == 422
    assert second.status_code == 422

    with Session(migrated_engine) as session:
        count = session.scalar(select(func.count()).select_from(ProductionRecord))
        assert count == 0


def test_post_unknown_line_returns_404(client: TestClient) -> None:
    response = client.post("/api/v1/production-records", json=_payload(999))

    assert response.status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"interval_start": "2026-08-10T22:00:00"},  # naive
        {"good_count": 200},  # good_count > total_count
        {"total_count": -1},
    ],
)
def test_post_invalid_payload_returns_422(
    client: TestClient, migrated_engine: Engine, overrides: dict[str, object]
) -> None:
    line_id = _seed_line(migrated_engine)

    response = client.post("/api/v1/production-records", json=_payload(line_id, **overrides))

    assert response.status_code == 422
