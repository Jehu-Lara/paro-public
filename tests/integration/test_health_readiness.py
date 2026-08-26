"""Liveness/readiness contracts against the migrated test database."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from paro.api.deps import get_db
from paro.config import get_settings
from paro.main import app


def test_health_and_ready_with_reachable_database(client: TestClient) -> None:
    health = client.get("/health")
    ready = client.get("/ready")
    assert health.status_code == 200
    assert health.json()["database"] == "ok"
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "database": "ok"}


def test_health_stays_live_while_ready_reports_database_failure() -> None:
    class BrokenSession:
        def execute(self, statement: object) -> None:
            raise OperationalError("SELECT 1", {}, RuntimeError("offline"))

    def broken_db() -> Generator[Session]:
        yield BrokenSession()  # type: ignore[misc]

    app.dependency_overrides[get_db] = broken_db
    try:
        client = TestClient(app)
        health = client.get("/health")
        ready = client.get("/ready")
    finally:
        app.dependency_overrides.clear()
    assert health.status_code == 200
    assert health.json()["database"] == "unreachable"
    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready", "database": "unreachable"}


def test_production_without_api_key_fails_startup_and_readiness(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARO_ENV", "production")
    monkeypatch.setenv("PARO_API_KEY", "")
    get_settings.cache_clear()
    try:
        ready = client.get("/ready")
        with pytest.raises(RuntimeError, match="PARO_API_KEY"), TestClient(app):
            pass
    finally:
        get_settings.cache_clear()

    assert ready.status_code == 503
    assert ready.json() == {
        "status": "not_ready",
        "database": "unknown",
        "configuration": "missing_api_key",
    }


def test_production_with_api_key_is_ready(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARO_ENV", "PRODUCTION")
    monkeypatch.setenv("PARO_API_KEY", "configured-key")
    get_settings.cache_clear()
    try:
        ready = client.get("/ready")
    finally:
        get_settings.cache_clear()

    assert ready.status_code == 200
