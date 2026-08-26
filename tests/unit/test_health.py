"""Pruebas del endpoint de salud."""

import pytest
from fastapi.testclient import TestClient

import paro.main as main_module
from paro import __version__
from paro.config import get_settings
from paro.main import app

client = TestClient(app)


def test_health_returns_ok_and_version() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "database": "ok"}


def test_health_returns_200_without_key_when_api_key_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /health is never gated by PARO_API_KEY (docs/adr/0005): a
    configured key must not affect this read-only endpoint, with or
    without an X-API-Key header. Uses the bare TestClient above, not
    migrated_engine -- /health catches SQLAlchemyError internally and
    returns 200 even against this module's unmigrated default DB, so no
    real database is needed here (see docs/known-issues.md for why a
    real migrated_engine-backed /health test is avoided on Windows).
    """
    monkeypatch.setenv("PARO_API_KEY", "secret-key")
    get_settings.cache_clear()
    try:
        response = client.get("/health")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200


def test_health_version_matches_openapi() -> None:
    """La version publicada en OpenAPI y la del endpoint no deben divergir."""
    schema = client.get("/openapi.json").json()

    assert schema["info"]["version"] == __version__


def test_unknown_route_returns_404() -> None:
    assert client.get("/no-existe").status_code == 404


def test_responses_include_defensive_security_headers() -> None:
    response = client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_unhandled_500_in_real_app_keeps_security_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "PRIVATE_500_SENTINEL"

    def explode(_db: object) -> bool:
        raise RuntimeError(sentinel)

    monkeypatch.setattr(main_module, "_database_reachable", explode)

    response = client.get("/health")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert sentinel not in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
