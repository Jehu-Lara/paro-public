"""Retry/backoff logic (docs/simulator-spec.md section 9) against a
scripted fake HttpClient -- no real network, no real rate limiter.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from scripts.simulator.client import (
    API_KEY_ENV_VAR,
    RETRY_MAX_ATTEMPTS,
    TRUSTED_INGEST_HEADER,
    ApiError,
    post_production_record,
)
from scripts.simulator.model import ProductionRecordDraft

_DRAFT = ProductionRecordDraft(
    line_id=1,
    interval_start=datetime(2026, 8, 10, 6, 0, tzinfo=UTC),
    interval_end=datetime(2026, 8, 10, 6, 15, tzinfo=UTC),
    total_count=10,
    good_count=9,
    ideal_cycle_time_seconds=Decimal("30.000"),
    source="simulator",
    external_id="sim-line1-0",
)


class _FakeResponse:
    def __init__(self, status_code: int, body: Any | None = None) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        return self._body if self._body is not None else {"status": self.status_code}


class _ScriptedClient:
    def __init__(self, statuses: list[int | _FakeResponse]) -> None:
        self._statuses = list(statuses)
        self.calls: list[dict[str, Any]] = []

    def request(
        self, method: str, url: str, *, json: Any = None, headers: Any = None
    ) -> _FakeResponse:
        self.calls.append({"method": method, "url": url, "json": json, "headers": headers})
        response = self._statuses.pop(0)
        return response if isinstance(response, _FakeResponse) else _FakeResponse(response)


def _recording_sleep() -> tuple[list[float], Any]:
    delays: list[float] = []

    def sleep(seconds: float) -> None:
        delays.append(seconds)

    return delays, sleep


def test_success_on_first_attempt_no_sleep() -> None:
    client = _ScriptedClient([201])
    delays, sleep = _recording_sleep()

    _, was_created = post_production_record(client, "http://api", _DRAFT, sleep=sleep)

    assert was_created is True
    assert len(client.calls) == 1
    assert delays == []


def test_200_means_not_created() -> None:
    client = _ScriptedClient([200])
    _, sleep = _recording_sleep()

    _, was_created = post_production_record(client, "http://api", _DRAFT, sleep=sleep)

    assert was_created is False


def test_retries_429_with_exponential_backoff_then_succeeds() -> None:
    client = _ScriptedClient([429, 429, 201])
    delays, sleep = _recording_sleep()

    _, was_created = post_production_record(client, "http://api", _DRAFT, sleep=sleep)

    assert was_created is True
    assert len(client.calls) == 3
    assert delays == [1.0, 2.0]


def test_exhausting_retry_budget_on_429_raises_api_error() -> None:
    client = _ScriptedClient([429] * RETRY_MAX_ATTEMPTS)
    delays, sleep = _recording_sleep()

    with pytest.raises(ApiError) as exc_info:
        post_production_record(client, "http://api", _DRAFT, sleep=sleep)

    assert exc_info.value.status_code == 429
    assert len(client.calls) == RETRY_MAX_ATTEMPTS
    assert len(delays) == RETRY_MAX_ATTEMPTS - 1


def test_409_is_not_retried() -> None:
    client = _ScriptedClient([409])
    _, sleep = _recording_sleep()

    with pytest.raises(ApiError) as exc_info:
        post_production_record(client, "http://api", _DRAFT, sleep=sleep)

    assert exc_info.value.status_code == 409
    assert len(client.calls) == 1


def test_api_error_string_omits_409_field_values() -> None:
    sentinel = "PRIVATE_NOTE_SENTINEL"
    client = _ScriptedClient(
        [
            _FakeResponse(
                409,
                {
                    "error": "duplicate_with_different_payload",
                    "differing_fields": {"operator_note": [sentinel, "replacement"]},
                },
            )
        ]
    )

    with pytest.raises(ApiError) as exc_info:
        post_production_record(client, "http://api", _DRAFT)

    error_text = str(exc_info.value)
    assert "duplicate_with_different_payload" in error_text
    assert "operator_note" in error_text
    assert sentinel not in error_text


def test_5xx_is_not_retried() -> None:
    """Deliberate (see client.py's _post_with_retry comment): section 9 only
    specifies retry semantics for 429, and a 5xx here is an unhandled-
    exception bug, not transient noise."""
    client = _ScriptedClient([500])
    _, sleep = _recording_sleep()

    with pytest.raises(ApiError) as exc_info:
        post_production_record(client, "http://api", _DRAFT, sleep=sleep)

    assert exc_info.value.status_code == 500
    assert len(client.calls) == 1


def test_trusted_ingest_header_sent_only_when_token_given() -> None:
    client = _ScriptedClient([201, 201])
    _, sleep = _recording_sleep()

    post_production_record(client, "http://api", _DRAFT, sleep=sleep)
    post_production_record(client, "http://api", _DRAFT, trusted_ingest_token="secret", sleep=sleep)

    assert client.calls[0]["headers"] is None
    assert client.calls[1]["headers"] == {TRUSTED_INGEST_HEADER: "secret"}


def test_api_key_and_trusted_ingest_headers_are_sent_independently() -> None:
    client = _ScriptedClient([201, 201])
    _, sleep = _recording_sleep()

    post_production_record(client, "http://api", _DRAFT, api_key="api-secret", sleep=sleep)
    post_production_record(
        client,
        "http://api",
        _DRAFT,
        api_key="api-secret",
        trusted_ingest_token="ingest-secret",
        sleep=sleep,
    )

    assert API_KEY_ENV_VAR == "PARO_API_KEY"
    assert client.calls[0]["headers"] == {"X-API-Key": "api-secret"}
    assert client.calls[1]["headers"] == {
        "X-API-Key": "api-secret",
        TRUSTED_INGEST_HEADER: "ingest-secret",
    }
