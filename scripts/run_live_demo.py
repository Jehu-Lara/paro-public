"""Render cron entrypoint for PARO's live-updating synthetic demo."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime

import httpx2

from paro.db.session import get_session_local
from scripts.simulate_production import _ensure_reason_catalog, _resolve_topology
from scripts.simulator.client import (
    API_KEY_ENV_VAR,
    REQUEST_TIMEOUT_SECONDS,
    TRUSTED_INGEST_TOKEN_ENV_VAR,
    ApiError,
    patch_downtime_event,
)
from scripts.simulator.model import SimulatorConfig
from scripts.simulator.rolling import build_rolling_plan
from scripts.simulator.transport import DEFAULT_MAX_WORKERS, transport


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("PARO_BASE_URL"))
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    api_key = os.environ.get(API_KEY_ENV_VAR)
    trusted_token = os.environ.get(TRUSTED_INGEST_TOKEN_ENV_VAR)
    if not args.base_url:
        print("[live-demo] PARO_BASE_URL or --base-url is required")
        return 2
    if not api_key or not trusted_token:
        print("[live-demo] PARO_API_KEY and PARO_TRUSTED_INGEST_TOKEN are required")
        return 2

    with get_session_local()() as session:
        lines, machines = _resolve_topology(session)
        config = SimulatorConfig(
            lines=lines,
            machines=machines,
            reason_ids=_ensure_reason_catalog(session),
        )
        plan = build_rolling_plan(session, config, now=datetime.now(UTC))

    result = transport(
        plan.run,
        base_url=args.base_url,
        max_workers=args.max_workers,
        api_key=api_key,
        trusted_ingest_token=trusted_token,
    )
    patch_failures = []
    with httpx2.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        for closing in plan.closings:
            try:
                patch_downtime_event(
                    client,
                    args.base_url,
                    closing.event_id,
                    expected_updated_at=closing.expected_updated_at,
                    ended_at=closing.ended_at,
                    api_key=api_key,
                    trusted_ingest_token=trusted_token,
                )
            except ApiError as exc:
                patch_failures.append(str(exc))

    print(
        "[live-demo] "
        f"cutoff={plan.cutoff.isoformat()} "
        f"production_created={result.production_records_created} "
        f"downtime_created={result.downtime_events_created} "
        f"closed={len(plan.closings) - len(patch_failures)} "
        f"gap_detected={plan.gap_detected}"
    )
    for write_failure in result.failures:
        print(f"[live-demo] write failure {write_failure.draft.external_id}: {write_failure.error}")
    for patch_failure in patch_failures:
        print(f"[live-demo] close failure: {patch_failure}")
    return 0 if result.succeeded and not patch_failures else 1


if __name__ == "__main__":
    sys.exit(main())
