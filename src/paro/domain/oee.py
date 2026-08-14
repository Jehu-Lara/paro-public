"""Deterministic OEE (Overall Equipment Effectiveness) engine.

Formulas (Vorne/oee.com format, documented in ``docs/oee-definition.md``)::

    Planned Production Time = duration(window) - union(planned downtimes ∩ window)
    Run Time                = Planned Production Time - union(unplanned downtimes ∩ window)

    Availability = Run Time / Planned Production Time
    Performance  = (Ideal Cycle Time x Total Count) / Run Time
    Quality      = Good Count / Total Count
    OEE          = Availability x Performance x Quality

The whole module uses ``Decimal`` and whole seconds: never ``float``. A
zero denominator never produces ``0.0`` nor an uncontrolled exception; it
produces ``None`` in that component and a named warning in
``OeeResult.warnings`` (see :mod:`paro.domain.warnings`). ``Performance``
above 100% is kept raw alongside a version capped at 100% for
presentation, never silently clipped.

``calculate_oee`` receives Ideal Cycle Time already aggregated (``Ideal
Cycle Time x Total Count``, summed exactly by the caller when there are
several production records) instead of a per-unit value: the engine never
divides to reconstruct a weighted average, because that quotient may have
no finite decimal representation and a later multiplication does not
recover the precision already lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from paro.domain.intervals import Interval, duration_seconds, subtract
from paro.domain.warnings import Warning

__all__ = ["DowntimeSpan", "OeeResult", "calculate_oee"]


@dataclass(frozen=True, slots=True)
class DowntimeSpan:
    """A downtime as it arrives from the repository: may still be open.

    ``end is None`` represents an event with no ``ended_at`` yet. The
    engine closes it using ``as_of`` (see :func:`calculate_oee`) instead
    of failing, because a shift in progress always has downtimes that
    haven't ended yet.
    """

    start: datetime
    end: datetime | None


@dataclass(frozen=True, slots=True)
class OeeResult:
    """The calculation's result, with components, durations, and warnings.

    Components are ``Decimal | None``: ``None`` means "not calculable
    with this data", never "zero". ``oee`` only has a value when all three
    components could be calculated.
    """

    availability: Decimal | None
    performance_raw: Decimal | None
    performance_capped: Decimal | None
    quality: Decimal | None
    oee: Decimal | None
    planned_production_time_seconds: int
    run_time_seconds: int
    warnings: list[Warning] = field(default_factory=list)


def _resolve_span(span: DowntimeSpan, as_of: datetime) -> Interval | None:
    """Closes a ``DowntimeSpan`` into an ``Interval``, using ``as_of`` if it's open.

    Returns ``None`` when, after resolving the end, the interval is empty
    or inverted (e.g. an event that opened after ``as_of``): that's
    unusual data, not a reason to interrupt the whole report's
    calculation.
    """
    end = span.end if span.end is not None else as_of
    if end <= span.start:
        return None
    return Interval(span.start, end)


def _resolve_spans(spans: list[DowntimeSpan], as_of: datetime) -> tuple[list[Interval], bool]:
    intervals: list[Interval] = []
    any_open = False
    for span in spans:
        if span.end is None:
            any_open = True
        resolved = _resolve_span(span, as_of)
        if resolved is not None:
            intervals.append(resolved)
    return intervals, any_open


def _run_time_segments(
    planned_production_segments: list[Interval], unplanned_downtimes: list[Interval]
) -> list[Interval]:
    """Subtracts unplanned downtimes from each planned-time segment.

    Processed segment by segment (instead of treating the window as a
    single interval) because planned downtimes may already have split
    the window into several pieces.
    """
    segments: list[Interval] = []
    for segment in planned_production_segments:
        segments.extend(subtract(segment, unplanned_downtimes))
    return segments


def calculate_oee(
    window: Interval,
    planned_downtimes: list[DowntimeSpan],
    unplanned_downtimes: list[DowntimeSpan],
    total_count: int,
    good_count: int,
    ideal_time_total_seconds: Decimal,
    as_of: datetime | None = None,
) -> OeeResult:
    """Calculates OEE for ``window`` from downtimes and production counts.

    ``as_of`` closes events still open; it defaults to ``window``'s end
    (documented as the deterministic rule for open events). Downtimes
    must already arrive split into planned/unplanned: that classification
    is a fact about the event, not something the OEE engine decides.

    ``ideal_time_total_seconds`` is ``Ideal Cycle Time x Total Count``
    already aggregated by the caller (see the module docstring): the engine
    uses it directly in ``Performance``, without dividing or multiplying by
    ``total_count``.
    """
    if total_count < 0 or good_count < 0:
        raise ValueError("total_count and good_count cannot be negative.")
    if good_count > total_count:
        raise ValueError(f"good_count ({good_count}) cannot exceed total_count ({total_count}).")
    if ideal_time_total_seconds < 0:
        raise ValueError("ideal_time_total_seconds cannot be negative.")

    resolved_as_of = as_of if as_of is not None else window.end

    warnings_found: list[Warning] = []

    planned_intervals, planned_had_open = _resolve_spans(planned_downtimes, resolved_as_of)
    unplanned_intervals, unplanned_had_open = _resolve_spans(unplanned_downtimes, resolved_as_of)
    if planned_had_open or unplanned_had_open:
        warnings_found.append(Warning.OPEN_EVENT_CLIPPED)

    planned_production_segments = subtract(window, planned_intervals)
    planned_production_time_seconds = duration_seconds(planned_production_segments)

    run_time_segments = _run_time_segments(planned_production_segments, unplanned_intervals)
    run_time_seconds = duration_seconds(run_time_segments)

    availability: Decimal | None
    if planned_production_time_seconds == 0:
        availability = None
        warnings_found.append(Warning.ZERO_PLANNED_TIME)
    else:
        availability = Decimal(run_time_seconds) / Decimal(planned_production_time_seconds)

    performance_raw: Decimal | None
    performance_capped: Decimal | None
    if run_time_seconds == 0:
        performance_raw = None
        performance_capped = None
        warnings_found.append(Warning.ZERO_RUN_TIME)
    else:
        performance_raw = ideal_time_total_seconds / Decimal(run_time_seconds)
        if performance_raw > 1:
            performance_capped = Decimal(1)
            warnings_found.append(Warning.PERFORMANCE_OVER_100)
        else:
            performance_capped = performance_raw

    quality: Decimal | None
    if total_count == 0:
        quality = None
        warnings_found.append(Warning.ZERO_TOTAL_COUNT)
    else:
        quality = Decimal(good_count) / Decimal(total_count)

    oee: Decimal | None = None
    if availability is not None and performance_raw is not None and quality is not None:
        oee = availability * performance_raw * quality

    return OeeResult(
        availability=availability,
        performance_raw=performance_raw,
        performance_capped=performance_capped,
        quality=quality,
        oee=oee,
        planned_production_time_seconds=planned_production_time_seconds,
        run_time_seconds=run_time_seconds,
        warnings=warnings_found,
    )
