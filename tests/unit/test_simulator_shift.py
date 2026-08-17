"""Shift A/B/C derivation (docs/simulator-spec.md section 4.5, resolved gap:

boundaries are 06:00/14:00/22:00 America/Monterrey local time, fixed in
scripts/simulator/config.py -- the spec itself never pins these down."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from scripts.simulator.shift import shift_for

_TZ = ZoneInfo("America/Monterrey")


def _local(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=_TZ).astimezone(UTC)


def test_shift_a_at_and_after_its_start() -> None:
    assert shift_for(_local(2026, 8, 10, 6, 0)) == "A"
    assert shift_for(_local(2026, 8, 10, 10, 0)) == "A"
    assert shift_for(_local(2026, 8, 10, 13, 59)) == "A"


def test_shift_b_at_and_after_its_start() -> None:
    assert shift_for(_local(2026, 8, 10, 14, 0)) == "B"
    assert shift_for(_local(2026, 8, 10, 18, 0)) == "B"
    assert shift_for(_local(2026, 8, 10, 21, 59)) == "B"


def test_shift_c_at_and_after_its_start_wraps_past_midnight() -> None:
    assert shift_for(_local(2026, 8, 10, 22, 0)) == "C"
    assert shift_for(_local(2026, 8, 10, 23, 30)) == "C"
    assert shift_for(_local(2026, 8, 11, 0, 0)) == "C"
    assert shift_for(_local(2026, 8, 11, 5, 59)) == "C"


def test_shift_derivation_uses_local_time_not_utc() -> None:
    # America/Monterrey is UTC-6 (no DST as of 2026): 06:00 local on
    # 2026-08-10 is 12:00 UTC. Asserting via a raw UTC timestamp (not
    # going through _local's own astimezone conversion) actually exercises
    # the UTC-to-local conversion inside shift_for, not just round-trips it.
    utc_at_shift_a_start = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    assert shift_for(utc_at_shift_a_start) == "A"
