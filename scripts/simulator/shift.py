"""Shift A/B/C derivation (docs/simulator-spec.md section 4.5).

Pure time-of-day arithmetic, not a DB lookup: the ``Shift`` table has no
code-to-time mapping and no FK from ``downtime_event``/``production_record``,
and the core generator must stay free of I/O (ADR 0004). Boundaries and
timezone are fixed simulator-config values (``scripts/simulator/config.py``);
``simulator-spec.md`` never fixes them itself -- this resolves that gap.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.simulator.config import SHIFT_BOUNDARIES_LOCAL, SHIFT_TIMEZONE

__all__ = ["shift_for"]

_TZ = ZoneInfo(SHIFT_TIMEZONE)
_ORDERED_BOUNDARIES = sorted(SHIFT_BOUNDARIES_LOCAL.items(), key=lambda item: item[1])


def shift_for(timestamp_utc: datetime) -> str:
    """Returns the shift code ("A"/"B"/"C") active at ``timestamp_utc``.

    Boundaries are inclusive of their start: a timestamp exactly at a
    boundary belongs to the shift that starts there.
    """
    local_time = timestamp_utc.astimezone(_TZ).time()
    active_code = _ORDERED_BOUNDARIES[-1][0]  # wraps past midnight into the last shift
    for code, boundary in _ORDERED_BOUNDARIES:
        if local_time >= boundary:
            active_code = code
        else:
            break
    return active_code
