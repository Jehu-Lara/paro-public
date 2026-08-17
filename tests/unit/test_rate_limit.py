"""Predicado de exencion del rate limiter (trusted-ingest).

No cubre el propio limiter (fire N requests, assert 429) -- ese test esta
diferido explicitamente como tarea separada (docs/simulator-spec.md seccion
6). Esto solo verifica la logica nueva que Step 2 introduce: cuando
``is_trusted_ingest`` retorna True/False segun token configurado y header
recibido.
"""

from collections.abc import Iterator

import pytest
from starlette.requests import Request

from paro.api.rate_limit import TRUSTED_INGEST_HEADER, is_trusted_ingest
from paro.config import get_settings


def _request(headers: dict[str, str] | None = None) -> Request:
    encoded = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "headers": encoded})


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_no_exemption_when_token_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PARO_TRUSTED_INGEST_TOKEN", raising=False)

    request = _request({TRUSTED_INGEST_HEADER: "anything"})

    assert is_trusted_ingest(request) is False


def test_no_exemption_when_header_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARO_TRUSTED_INGEST_TOKEN", "secret-token")

    request = _request()

    assert is_trusted_ingest(request) is False


def test_no_exemption_when_header_does_not_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARO_TRUSTED_INGEST_TOKEN", "secret-token")

    request = _request({TRUSTED_INGEST_HEADER: "wrong-token"})

    assert is_trusted_ingest(request) is False


def test_exemption_when_header_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARO_TRUSTED_INGEST_TOKEN", "secret-token")

    request = _request({TRUSTED_INGEST_HEADER: "secret-token"})

    assert is_trusted_ingest(request) is True
