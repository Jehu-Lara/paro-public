"""El handler generico de ``Exception`` devuelve un 500 neutro al cliente y
nunca filtra traceback, SQL ni rutas internas.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from paro.api.deps import get_db
from paro.api.routers import downtime as downtime_router_module
from paro.db.models import DowntimeReason, ProductionLine
from paro.main import app


@pytest.fixture
def raising_client(migrated_engine: Engine) -> Generator[TestClient]:
    def override_get_db() -> Generator[Session]:
        with Session(migrated_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


def test_unexpected_error_returns_generic_500(
    raising_client: TestClient, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(migrated_engine) as session:
        line = ProductionLine(code="L1", name="Linea 1", timezone="America/Monterrey", active=True)
        reason = DowntimeReason(code="R1", name="Falla mecanica", default_is_planned=False)
        session.add_all([line, reason])
        session.commit()
        line_id, reason_id = line.id, reason.id

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("boom: /secret/path/paro.db leaked SELECT * FROM downtime_event")

    monkeypatch.setattr(downtime_router_module, "create_downtime_event", _boom)

    response = raising_client.post(
        "/api/v1/downtime-events",
        json={
            "line_id": line_id,
            "reason_id": reason_id,
            "started_at": "2026-08-10T22:00:00+00:00",
            "ended_at": "2026-08-10T22:05:00+00:00",
            "is_planned": False,
        },
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}

    text = response.text
    for leaked in ("Traceback", "boom", "paro.db", "SELECT", "RuntimeError", "site-packages"):
        assert leaked not in text
