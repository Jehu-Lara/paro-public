"""Argument parsing only -- no DB, no network (see
tests/integration/test_simulate_production_topology.py for the DB-backed
resolution helpers).
"""

from datetime import UTC, datetime

import pytest
from scripts.simulate_production import _parse_args
from scripts.simulator.config import MASTER_SEED
from scripts.simulator.transport import DEFAULT_MAX_WORKERS


def test_tz_aware_start_end_parse_correctly() -> None:
    args = _parse_args(
        [
            "--start",
            "2026-08-10T00:00:00+00:00",
            "--end",
            "2026-08-11T00:00:00+00:00",
            "--base-url",
            "http://localhost:8000",
        ]
    )

    assert args.start == datetime(2026, 8, 10, tzinfo=UTC)
    assert args.end == datetime(2026, 8, 11, tzinfo=UTC)
    assert args.base_url == "http://localhost:8000"


def test_naive_start_is_rejected_before_generate_would_run() -> None:
    with pytest.raises(SystemExit):
        _parse_args(
            [
                "--start",
                "2026-08-10T00:00:00",
                "--end",
                "2026-08-11T00:00:00+00:00",
                "--base-url",
                "http://localhost:8000",
            ]
        )


def test_seed_and_max_workers_default_to_imported_constants() -> None:
    args = _parse_args(
        [
            "--start",
            "2026-08-10T00:00:00+00:00",
            "--end",
            "2026-08-11T00:00:00+00:00",
            "--base-url",
            "http://localhost:8000",
        ]
    )

    assert args.seed == MASTER_SEED
    assert args.max_workers == DEFAULT_MAX_WORKERS


def test_missing_required_base_url_raises() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--start", "2026-08-10T00:00:00+00:00", "--end", "2026-08-11T00:00:00+00:00"])
