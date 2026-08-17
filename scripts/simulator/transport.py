"""Concurrent transport of a ``GeneratedRun`` through the PARO API.

ADR 0004: "concurrent HTTP writes via a bounded worker pool over
already-generated batches, through the existing API client (not direct DB
writes, so the simulator exercises the same validation path real
integrations would use)." One shared ``httpx2.Client`` is used for the
whole pool -- verified fact, not an implementation choice: ``Client`` is
documented thread-safe per its own docstring at
``.venv/Lib/site-packages/httpx2/_client.py:578`` ("It can be shared
between threads"). ``max_workers``'s default of 8 *is* an implementation
choice, not spec-mandated.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

import httpx2

from scripts.simulator.client import (
    REQUEST_TIMEOUT_SECONDS,
    ApiError,
    HttpClient,
    post_downtime_event,
    post_production_record,
)
from scripts.simulator.model import DowntimeEventDraft, GeneratedRun, ProductionRecordDraft

__all__ = ["TransportFailure", "TransportResult", "transport"]

DEFAULT_MAX_WORKERS = 8


@dataclass(frozen=True)
class TransportFailure:
    kind: Literal["production_record", "downtime_event"]
    draft: ProductionRecordDraft | DowntimeEventDraft
    error: str


@dataclass(frozen=True)
class TransportResult:
    production_records_created: int
    production_records_existing: int
    downtime_events_created: int
    downtime_events_existing: int
    failures: tuple[TransportFailure, ...]

    @property
    def succeeded(self) -> bool:
        return not self.failures


@contextmanager
def _resolve_client(client: HttpClient | None) -> Iterator[HttpClient]:
    """Yields ``client`` as-is if given (test doubles own their own
    lifecycle), otherwise opens and closes a real ``httpx2.Client``."""
    if client is not None:
        yield client
        return
    with httpx2.Client(timeout=REQUEST_TIMEOUT_SECONDS) as real_client:
        yield real_client


def transport(
    run: GeneratedRun,
    *,
    base_url: str,
    max_workers: int = DEFAULT_MAX_WORKERS,
    trusted_ingest_token: str | None = None,
    client: HttpClient | None = None,
) -> TransportResult:
    """Posts every row in ``run`` concurrently via a bounded worker pool.

    Never raises for a single row's failure -- collects each into
    ``TransportResult.failures`` instead, so one bad row doesn't abort an
    otherwise-successful multi-thousand-row run. Only a client-construction
    or thread-pool-level problem propagates as an exception.

    ``client`` defaults to a real ``httpx2.Client`` (production use); tests
    inject a fake ``HttpClient`` instead, without needing a real network or
    a running server.
    """
    production_records_created = 0
    production_records_existing = 0
    downtime_events_created = 0
    downtime_events_existing = 0
    failures: list[TransportFailure] = []

    with (
        _resolve_client(client) as active_client,
        ThreadPoolExecutor(max_workers=max_workers) as pool,
    ):
        production_futures = {
            pool.submit(
                post_production_record,
                active_client,
                base_url,
                draft,
                trusted_ingest_token=trusted_ingest_token,
            ): draft
            for draft in run.production_records
        }
        downtime_futures = {
            pool.submit(
                post_downtime_event,
                active_client,
                base_url,
                draft,
                trusted_ingest_token=trusted_ingest_token,
            ): draft
            for draft in run.downtime_events
        }

        for future in as_completed(production_futures):
            draft = production_futures[future]
            try:
                _, was_created = future.result()
            except ApiError as exc:
                failures.append(TransportFailure("production_record", draft, str(exc)))
            else:
                if was_created:
                    production_records_created += 1
                else:
                    production_records_existing += 1

        for future in as_completed(downtime_futures):
            downtime_draft = downtime_futures[future]
            try:
                _, was_created = future.result()
            except ApiError as exc:
                failures.append(TransportFailure("downtime_event", downtime_draft, str(exc)))
            else:
                if was_created:
                    downtime_events_created += 1
                else:
                    downtime_events_existing += 1

    return TransportResult(
        production_records_created=production_records_created,
        production_records_existing=production_records_existing,
        downtime_events_created=downtime_events_created,
        downtime_events_existing=downtime_events_existing,
        failures=tuple(failures),
    )
