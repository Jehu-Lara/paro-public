"""Pruebas del endpoint de salud."""

from fastapi.testclient import TestClient

from paro import __version__
from paro.main import app

client = TestClient(app)


def test_health_returns_ok_and_version() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "database": "ok"}


def test_health_version_matches_openapi() -> None:
    """La version publicada en OpenAPI y la del endpoint no deben divergir."""
    schema = client.get("/openapi.json").json()

    assert schema["info"]["version"] == __version__


def test_unknown_route_returns_404() -> None:
    assert client.get("/no-existe").status_code == 404
