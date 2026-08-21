"""Unhandled failures return a generic 500 without logging payload values."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from paro.api.errors import register_exception_handlers


def test_generic_exception_log_excludes_exception_message_and_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def capture_log(*args: object, **kwargs: object) -> None:
        observed.append((args, kwargs))

    monkeypatch.setattr("paro.api.errors.logger.error", capture_log)

    @app.get("/explode")
    def explode() -> None:
        raise RuntimeError("sensitive-payload-canary")

    register_exception_handlers(app)
    response = TestClient(app, raise_server_exceptions=False).get("/explode")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert observed == [
        (
            ("Unhandled exception",),
            {
                "extra": {
                    "method": "GET",
                    "path": "/explode",
                    "exception_type": "RuntimeError",
                }
            },
        )
    ]
    assert "sensitive-payload-canary" not in repr(observed)
