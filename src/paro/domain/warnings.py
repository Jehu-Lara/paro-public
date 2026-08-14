"""Names of the data-quality warnings the domain emits.

The OEE engine never hides a data problem by turning it into a silent
``0.0``, nor does it hide it behind a generic exception. Instead, the
affected component becomes ``None`` and one of these names is added to
``OeeResult.warnings``, so whoever consumes the result knows exactly what
happened and why.
"""

from enum import StrEnum

__all__ = ["Warning"]


class Warning(StrEnum):
    """Named warnings PARO can emit alongside an OEE result.

    Most are emitted directly by :func:`paro.domain.oee.calculate_oee`.
    ``PARTIAL_PRODUCTION_EXCLUDED`` is the exception: it's detected by the
    caller assembling `calculate_oee`'s inputs (see ``routers/oee.py``),
    since the domain function only ever sees already-aggregated totals,
    never individual production rows.
    """

    ZERO_PLANNED_TIME = "ZERO_PLANNED_TIME"
    """Planned production time is zero: Availability cannot be calculated."""

    ZERO_RUN_TIME = "ZERO_RUN_TIME"
    """Run time is zero: Performance cannot be calculated."""

    ZERO_TOTAL_COUNT = "ZERO_TOTAL_COUNT"
    """Total count is zero: Quality cannot be calculated."""

    PERFORMANCE_OVER_100 = "PERFORMANCE_OVER_100"
    """Raw Performance exceeds 100%; usually indicates a misconfigured
    Ideal Cycle Time. The raw value is kept alongside one capped at 100%
    for presentation."""

    OPEN_EVENT_CLIPPED = "OPEN_EVENT_CLIPPED"
    """At least one downtime event was still open (no end) and was closed
    using ``as_of`` so it could be included in the calculation."""

    PARTIAL_PRODUCTION_EXCLUDED = "PARTIAL_PRODUCTION_EXCLUDED"
    """At least one ``production_record`` overlaps the requested window
    but isn't fully contained in it, and was excluded entirely from
    ``Total Count``/``Good Count``/``Ideal Cycle Time`` rather than
    partially counted."""
