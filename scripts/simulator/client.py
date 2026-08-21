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
import time
from collections.abc import Mapping
from typing import Any, Protocol

from paro.api.auth import API_KEY_HEADER
from paro.json_safe import json_safe
from scripts.simulator.model import DowntimeEventDraft, ProductionRecordDraft

__all__ = [
    "API_KEY_ENV_VAR",
    "TRUSTED_INGEST_HEADER",
    "TRUSTED_INGEST_TOKEN_ENV_VAR",
    "ApiError",
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


class ApiError(Exception):
    """Non-retryable failure: 4xx/5xx response, or 429 retry-budget exhaustion."""

    def __init__(self, status_code: int, body: Any, draft: object) -> None:
        super().__init__(f"API request failed with status {status_code}: {body!r}")
        self.status_code = status_code
        self.body = body
        self.draft = draft


def _post_with_retry(
    client: HttpClient,
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
        response = client.request("POST", url, json=json_body, headers=headers or None)
        if response.status_code == 429:
            if attempt == RETRY_MAX_ATTEMPTS - 1:
                raise ApiError(response.status_code, response.json(), draft)
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
            raise ApiError(response.status_code, response.json(), draft)
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
    response = _post_with_retry(
        client,
        f"{base_url}/api/v1/production-records",
        body,
        draft=draft,
        api_key=api_key,
        trusted_ingest_token=trusted_ingest_token,
        sleep=sleep,
    )
    return response.json(), response.status_code == 201


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
    response = _post_with_retry(
        client,
        f"{base_url}/api/v1/downtime-events",
        body,
        draft=draft,
        api_key=api_key,
        trusted_ingest_token=trusted_ingest_token,
        sleep=sleep,
    )
    return response.json(), response.status_code == 201


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
) -> Any:
    """Closes one previously-open deterministic simulator event."""
    headers: dict[str, str] = {}
    if api_key:
        headers[API_KEY_HEADER] = api_key
    if trusted_ingest_token:
        headers[TRUSTED_INGEST_HEADER] = trusted_ingest_token
    body = json_safe(
        {
            "expected_updated_at": expected_updated_at,
            "ended_at": ended_at,
            "actor": actor,
        }
    )
    response = client.request(
        "PATCH",
        f"{base_url}/api/v1/downtime-events/{event_id}",
        json=body,
        headers=headers or None,
    )
    if response.status_code >= 400:
        raise ApiError(response.status_code, response.json(), body)
    return response.json()
