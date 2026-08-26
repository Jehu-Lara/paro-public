"""Retrying HTTP client for the two write endpoints the simulator uses
(docs/simulator-spec.md sections 6, 9).

One request per row -- no bulk/batch endpoint exists (section 6 names one
as a deferred, separate future task). Serialization reuses
``paro.json_safe.json_safe`` (``Decimal`` -> ``str``, ``datetime`` -> ISO
8601): "the same rule Pydantic responses follow," so the request body and
the server's own response bodies agree on shape without a second,
independently-maintained serializer.
"""

from __future__ import annotations

import dataclasses
import os
import time
from collections.abc import Mapping
from typing import Any, Protocol

import httpx2

from paro.api.auth import API_KEY_HEADER
from paro.json_safe import json_safe
from scripts.simulator.model import DowntimeEventDraft, ProductionRecordDraft

__all__ = [
    "API_KEY_ENV_VAR",
    "TRUSTED_INGEST_HEADER",
    "TRUSTED_INGEST_TOKEN_ENV_VAR",
    "ApiCredentials",
    "ApiError",
    "ClientError",
    "ResponseDecodeError",
    "SimulatorTransportError",
    "load_api_credentials",
    "patch_downtime_event",
    "post_downtime_event",
    "post_production_record",
]

TRUSTED_INGEST_TOKEN_ENV_VAR = "PARO_TRUSTED_INGEST_TOKEN"
TRUSTED_INGEST_HEADER = "X-Paro-Trusted-Ingest"
API_KEY_ENV_VAR = "PARO_API_KEY"

RETRY_BASE_DELAY_SECONDS = 1.0
RETRY_MAX_DELAY_SECONDS = 60.0
RETRY_MAX_ATTEMPTS = 8
REQUEST_TIMEOUT_SECONDS = 10.0


@dataclasses.dataclass(frozen=True)
class ApiCredentials:
    api_key: str | None
    trusted_ingest_token: str | None


def load_api_credentials(environ: Mapping[str, str] | None = None) -> ApiCredentials:
    """Loads both simulator credentials without logging either value."""
    source = os.environ if environ is None else environ
    return ApiCredentials(
        api_key=source.get(API_KEY_ENV_VAR),
        trusted_ingest_token=source.get(TRUSTED_INGEST_TOKEN_ENV_VAR),
    )


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class HttpClient(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse: ...


class ClientError(Exception):
    """Base class for safe, per-row simulator failures."""


class ApiError(ClientError):
    """Non-retryable failure: 4xx/5xx response, or 429 retry-budget exhaustion."""

    def __init__(self, status_code: int, body: Any, draft: object) -> None:
        details = [f"API request failed with status {status_code}"]
        if isinstance(body, dict):
            error_code = body.get("error")
            if isinstance(error_code, str):
                details.append(f"error={error_code}")
            raw_fields = body.get("differing_fields")
            if isinstance(raw_fields, dict):
                field_names = sorted(str(field) for field in raw_fields)
            elif isinstance(raw_fields, list):
                field_names = sorted(str(field) for field in raw_fields if isinstance(field, str))
            else:
                field_names = []
            if field_names:
                details.append(f"differing_fields={','.join(field_names)}")
        super().__init__("; ".join(details))
        self.status_code = status_code
        self.body = body
        self.draft = draft


class SimulatorTransportError(ClientError):
    """A transient HTTP transport error exhausted its retry budget."""

    def __init__(self, exception_type: str, draft: object) -> None:
        super().__init__(f"API transport failed after retries: {exception_type}")
        self.exception_type = exception_type
        self.draft = draft


class ResponseDecodeError(ClientError):
    """An API response could not be decoded without exposing its body."""

    def __init__(self, draft: object) -> None:
        super().__init__("API response was not valid JSON")
        self.draft = draft


def _safe_json(response: HttpResponse, draft: object) -> Any:
    try:
        return response.json()
    except (TypeError, ValueError) as exc:
        raise ResponseDecodeError(draft) from exc


def _request_with_retry(
    client: HttpClient,
    method: str,
    url: str,
    json_body: Any,
    *,
    draft: object,
    api_key: str | None,
    trusted_ingest_token: str | None,
    sleep: Any = time.sleep,
) -> HttpResponse:
    headers: dict[str, str] = {}
    if api_key:
        headers[API_KEY_HEADER] = api_key
    if trusted_ingest_token:
        headers[TRUSTED_INGEST_HEADER] = trusted_ingest_token

    for attempt in range(RETRY_MAX_ATTEMPTS):
        try:
            response = client.request(method, url, json=json_body, headers=headers or None)
        except httpx2.TransportError as exc:
            if attempt == RETRY_MAX_ATTEMPTS - 1:
                raise SimulatorTransportError(type(exc).__name__, draft) from exc
            delay = min(RETRY_BASE_DELAY_SECONDS * (2**attempt), RETRY_MAX_DELAY_SECONDS)
            sleep(delay)
            continue
        if response.status_code == 429:
            if attempt == RETRY_MAX_ATTEMPTS - 1:
                raise ApiError(response.status_code, _safe_json(response, draft), draft)
            delay = min(RETRY_BASE_DELAY_SECONDS * (2**attempt), RETRY_MAX_DELAY_SECONDS)
            sleep(delay)
            continue
        if response.status_code >= 400:
            # Deliberate, not an oversight: section 9 only specifies retry
            # semantics for 429. A 5xx here is an unhandled-exception bug
            # by construction (paro/api/errors.py's generic 500 handler),
            # not transient noise -- retrying it would hide exactly the
            # kind of defect this transport layer exists to surface. A
            # 409/422 is a real data problem retrying can't fix either way.
            raise ApiError(response.status_code, _safe_json(response, draft), draft)
        return response

    raise AssertionError("unreachable: loop always returns or raises")


def post_production_record(
    client: HttpClient,
    base_url: str,
    draft: ProductionRecordDraft,
    *,
    api_key: str | None = None,
    trusted_ingest_token: str | None = None,
    sleep: Any = time.sleep,
) -> tuple[Any, bool]:
    """POSTs one production record. Returns ``(response_body, was_created)``.

    ``was_created`` mirrors ``src/paro/api/routers/production.py:50``:
    ``201`` = new row, ``200`` = existing (idempotent no-op).
    """
    body = json_safe(dataclasses.asdict(draft))
    response = _request_with_retry(
        client,
        "POST",
        f"{base_url}/api/v1/production-records",
        body,
        draft=draft,
        api_key=api_key,
        trusted_ingest_token=trusted_ingest_token,
        sleep=sleep,
    )
    return _safe_json(response, draft), response.status_code == 201


def post_downtime_event(
    client: HttpClient,
    base_url: str,
    draft: DowntimeEventDraft,
    *,
    api_key: str | None = None,
    trusted_ingest_token: str | None = None,
    sleep: Any = time.sleep,
) -> tuple[Any, bool]:
    """POSTs one downtime event. Returns ``(response_body, was_created)``.

    ``was_created`` mirrors ``src/paro/api/routers/downtime.py:71``:
    ``201`` = new row, ``200`` = existing (idempotent no-op).
    """
    body = json_safe(dataclasses.asdict(draft))
    response = _request_with_retry(
        client,
        "POST",
        f"{base_url}/api/v1/downtime-events",
        body,
        draft=draft,
        api_key=api_key,
        trusted_ingest_token=trusted_ingest_token,
        sleep=sleep,
    )
    return _safe_json(response, draft), response.status_code == 201


def patch_downtime_event(
    client: HttpClient,
    base_url: str,
    event_id: int,
    *,
    expected_updated_at: Any,
    ended_at: Any,
    api_key: str | None = None,
    trusted_ingest_token: str | None = None,
    actor: str = "simulator-live-v1",
    sleep: Any = time.sleep,
) -> Any:
    """Closes one previously-open deterministic simulator event."""
    body = json_safe(
        {
            "expected_updated_at": expected_updated_at,
            "ended_at": ended_at,
            "actor": actor,
        }
    )
    response = _request_with_retry(
        client,
        "PATCH",
        f"{base_url}/api/v1/downtime-events/{event_id}",
        body,
        draft=body,
        api_key=api_key,
        trusted_ingest_token=trusted_ingest_token,
        sleep=sleep,
    )
    return _safe_json(response, body)
