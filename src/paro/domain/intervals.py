"""Time-interval algebra for downtime calculation.

All intervals are **half-open**: ``[start, end)``. That choice isn't
cosmetic; it's what makes two consecutive shifts (06:00-14:00 and
14:00-22:00) partition the day without overlap or gap, and what makes an
event that ends exactly when another starts share not even one second
with it.

Module rules:

* Every ``datetime`` must be *tz-aware*. A naive ``datetime`` is a
  programming error, not a default value: it's rejected with
  ``ValueError``.
* An empty or inverted interval (``end <= start``) doesn't exist: it's
  rejected.
* Operations are pure and deterministic. No function reads the clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

__all__ = [
    "Interval",
    "clip",
    "duration_seconds",
    "require_aware",
    "subtract",
    "total_seconds",
    "union",
]


def require_aware(moment: datetime, field: str) -> datetime:
    """Validates that ``moment`` is tz-aware and normalizes it to UTC."""
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError(
            f"{field} must be tz-aware; received a naive datetime ({moment!r}). "
            "PARO always stores and computes in UTC."
        )
    return moment.astimezone(UTC)


@dataclass(frozen=True, slots=True, order=True)
class Interval:
    """Half-open time interval ``[start, end)`` in UTC.

    Immutable and orderable by ``start`` (and then by ``end``), which lets
    lists of intervals be sorted without writing a sort key.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        start = require_aware(self.start, "start")
        end = require_aware(self.end, "end")
        if end <= start:
            raise ValueError(
                f"An interval requires end > start; received start={start.isoformat()} "
                f"end={end.isoformat()}."
            )
        # The dataclass is frozen: normalizing to UTC requires bypassing setattr.
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    @property
    def seconds(self) -> int:
        """Duration in whole seconds.

        Whole seconds (not ``float``) are used so duration sums are exact
        and the OEE calculation can be done with ``Decimal``.
        """
        return int((self.end - self.start).total_seconds())


def clip(interval: Interval, window: Interval) -> Interval | None:
    """Clips ``interval`` to ``window``.

    Returns ``None`` when there's no intersection, instead of a zero-length
    interval: a zero-duration interval doesn't exist in this model, and
    returning ``None`` forces the caller to handle the case explicitly.

    This is the operation that makes a downtime crossing a shift boundary
    contribute only its portion to each shift.
    """
    start = max(interval.start, window.start)
    end = min(interval.end, window.end)
    if end <= start:
        return None
    return Interval(start, end)


def union(intervals: list[Interval]) -> list[Interval]:
    """Merges overlapping **and adjacent** intervals into a disjoint list.

    This is the piece that prevents double-counting: if two downtimes
    overlap, the shared seconds appear only once in the result.

    Adjacent intervals are merged on purpose: two consecutive downtimes
    with no gap (14:00-14:05 and 14:05-14:10) are ten continuous minutes
    of the line being stopped, and counting them as a single stretch is
    the correct thing for availability.

    Returns a new list sorted by ``start``; does not mutate the input.
    """
    if not intervals:
        return []

    merged: list[Interval] = []
    for current in sorted(intervals):
        if merged and current.start <= merged[-1].end:
            last = merged[-1]
            if current.end > last.end:
                merged[-1] = Interval(last.start, current.end)
            # If current is contained in last, it contributes nothing.
        else:
            merged.append(current)
    return merged


def subtract(base: Interval, to_remove: list[Interval]) -> list[Interval]:
    """Subtracts ``to_remove`` from ``base`` and returns the remaining stretches.

    Applies ``union`` internally, so it accepts lists with overlaps
    without subtracting the same seconds twice. If ``to_remove`` covers
    all of ``base``, returns an empty list.
    """
    remaining: list[Interval] = []
    cursor = base.start

    for block in union(to_remove):
        clipped = clip(block, base)
        if clipped is None:
            continue
        if clipped.start > cursor:
            remaining.append(Interval(cursor, clipped.start))
        cursor = max(cursor, clipped.end)

    if cursor < base.end:
        remaining.append(Interval(cursor, base.end))
    return remaining


def duration_seconds(intervals: list[Interval]) -> int:
    """Seconds covered by ``intervals``, counting overlaps only once."""
    return sum(item.seconds for item in union(intervals))


def total_seconds(intervals: list[Interval]) -> int:
    """Raw sum of durations, **without** deduplicating overlaps.

    Exists to measure how much time was reassigned due to overlap
    (``total_seconds - duration_seconds``) and report it as a
    data-quality warning. Must not be used to calculate availability.
    """
    return sum(item.seconds for item in intervals)
