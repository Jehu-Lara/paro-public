"""CORS: abierto para lectura, cerrado para los dos POST.

Prueba el mecanismo real (preflight bloqueado por metodo), no solo que el
middleware este registrado.
"""

from fastapi.testclient import TestClient

from paro.main import app

client = TestClient(app)


def test_get_allows_any_origin() -> None:
    response = client.get("/health", headers={"Origin": "https://example.com"})

    assert response.headers["access-control-allow-origin"] == "*"


def test_post_preflight_is_rejected() -> None:
    """Starlette answers the preflight (200), but excludes POST from the allow-list.

    A spec-compliant browser reads ``Access-Control-Allow-Methods``, sees
    POST isn't in it, and never sends the actual POST -- that's the real
    enforcement point, not the preflight status code itself.
    """
    response = client.options(
        "/api/v1/downtime-events",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "POST",
        },
    )

    allowed_methods = response.headers.get("access-control-allow-methods", "")
    assert "POST" not in allowed_methods.split(", ")
