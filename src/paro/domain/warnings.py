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
    """Named warnings :func:`paro.domain.oee.calculate_oee` can emit."""

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
