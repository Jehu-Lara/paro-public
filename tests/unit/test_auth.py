"""Optional API-key gate for write endpoints (docs/adr/0005-optional-api-key-authentication.md).

Same fixture/style as tests/unit/test_rate_limit.py: unset key = always
allowed, set key + matching header = allowed, set key + missing/wrong
header = 401.
"""

from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from paro.api.auth import API_KEY_HEADER, require_api_key
from paro.config import get_settings


def _request(headers: dict[str, str] | None = None) -> Request:
    encoded = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "headers": encoded})


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_no_gate_when_key_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PARO_API_KEY", raising=False)

    require_api_key(_request())  # no exception


def test_401_when_key_set_and_header_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARO_API_KEY", "secret-key")

    with pytest.raises(HTTPException) as exc_info:
        require_api_key(_request())

    assert exc_info.value.status_code == 401


def test_401_when_key_set_and_header_does_not_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARO_API_KEY", "secret-key")

    with pytest.raises(HTTPException) as exc_info:
        require_api_key(_request({API_KEY_HEADER: "wrong-key"}))

    assert exc_info.value.status_code == 401


def test_allowed_when_header_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARO_API_KEY", "secret-key")

    require_api_key(_request({API_KEY_HEADER: "secret-key"}))  # no exception
