# OEE Definition

## Purpose

This document explains what OEE (Overall Equipment Effectiveness) means in
PARO and how it is computed, for readers who consume the numbers (Power BI
dashboards, portfolio reviewers) but don't read `domain/oee.py` directly.
Referenced from `README.md` and from the module docstring of
`src/paro/domain/oee.py`.

## Formulas

Vorne/oee.com format:

```
Planned Production Time = window duration - union(planned downtimes ∩ window)
Run Time                = Planned Production Time - union(unplanned downtimes ∩ window)

Availability = Run Time / Planned Production Time
Performance  = (Ideal Cycle Time x Total Count) / Run Time
Quality      = Good Count / Total Count
OEE          = Availability x Performance x Quality
```

## Terms

- **Window** - the reporting period being measured (e.g. a shift).
- **Planned downtimes** - scheduled stops (lunch, planned maintenance).
  Subtracted from the window to get Planned Production Time.
- **Unplanned downtimes** - unscheduled stops (machine faults). Subtracted
  from Planned Production Time to get Run Time.
- **Ideal Cycle Time** - the theoretical time to produce one unit, in
  seconds. `calculate_oee` receives it already multiplied by Total Count
  (`ideal_time_total_seconds`), aggregated exactly across every production
  record in the window - the function itself never averages a per-unit
  value and divides to reconstruct it, since that division may not have a
  finite decimal representation and no amount of precision recovers what
  a later multiplication already lost.
- **Total Count** - total units produced (good + rejected) during the
  window.
- **Good Count** - units produced that passed quality, `<= Total Count`.

## Interval semantics

Downtimes are half-open intervals `[start, end)`. Overlapping downtimes of
the same kind (planned or unplanned) are combined with `union` before being
subtracted, so shared minutes are counted only once. See
`src/paro/domain/intervals.py` for the interval algebra itself; this
document only covers how OEE consumes it.

An open downtime (no `ended_at` yet) is closed using `as_of`, which defaults
to the end of the window.

## Edge cases

OEE never turns a data problem into a silent `0.0`, and never raises an
uncontrolled exception for one. Instead, the affected component becomes
`None` and a named warning is added (`src/paro/domain/warnings.py`).
Most of these come straight from `OeeResult.warnings`; the last one below
is the exception - `calculate_oee` only ever sees already-aggregated
totals, so `GET /oee` (`src/paro/api/routers/oee.py`) detects it itself,
before the aggregation happens, and adds it to the same `warnings` list
in the response:

| Warning | Condition | Effect |
| --- | --- | --- |
| `ZERO_PLANNED_TIME` | Planned Production Time is zero | Availability is `None` |
| `ZERO_RUN_TIME` | Run Time is zero | Performance is `None` |
| `ZERO_TOTAL_COUNT` | Total Count is zero | Quality is `None` |
| `PERFORMANCE_OVER_100` | Raw Performance exceeds 100% | Raw value is kept as-is; a separate value capped at 100% is also provided for presentation |
| `OPEN_EVENT_CLIPPED` | At least one downtime had no `ended_at` | The event was closed using `as_of` to include it in the calculation |
| `PARTIAL_PRODUCTION_EXCLUDED` | A `production_record` overlaps the requested window but isn't fully contained in it | The whole record is excluded from Total Count/Good Count/Ideal Cycle Time, not partially counted |

`OEE` itself is only computed when Availability, Performance (raw, not
capped), and Quality are all calculable; otherwise it is `None`.

## Worked examples

Sourced directly from `tests/unit/test_oee.py` - each number below is an
assertion in that suite, not a value written for this document.

**No downtime** (`test_happy_path_without_downtime`, 8h window):

```
Total Count = 480, Good Count = 456, Ideal Cycle Time = 30s
Planned Production Time = Run Time = 28800s
Availability = 1
Performance  = (30 x 480) / 28800 = 0.5
Quality      = 456 / 480 = 0.95
OEE          = 1 x 0.5 x 0.95 = 0.475
```

**Unplanned downtime** (`test_unplanned_downtime_reduces_run_time_but_not_planned_production_time`,
a 2h machine fault):

```
Total Count = 480, Good Count = 432, Ideal Cycle Time = 27s
Planned Production Time = 28800s (unaffected by unplanned downtime)
Run Time     = 28800 - 7200 = 21600s
Availability = 21600 / 28800 = 0.75
Performance  = (27 x 480) / 21600 = 0.6
Quality      = 432 / 480 = 0.9
OEE          = 0.75 x 0.6 x 0.9 = 0.405
```

**Performance over 100%** (`test_performance_over_100_percent_keeps_raw_value_and_adds_capped_with_warning`,
a misconfigured Ideal Cycle Time):

```
Total Count = 900, Good Count = 810, Ideal Cycle Time = 40s
Planned Production Time = Run Time = 28800s
Performance (raw)    = (40 x 900) / 28800 = 1.25  (125%)
Performance (capped) = 1  (for presentation only)
Quality      = 810 / 900 = 0.9
OEE          = 1 x 1.25 x 0.9 = 1.125   <- computed with the raw value
```

`PERFORMANCE_OVER_100` is added to `warnings`. OEE is deliberately computed
with the raw value, not the capped one: silently capping it would hide a
misconfigured Ideal Cycle Time behind a plausible-looking number.

## API safety bounds

`GET /api/v1/oee` accepts at most 31 calendar days. The implementation
allows the one-hour fall-DST expansion so a valid local-calendar window is
not rejected. Before materializing facts, the query counts matching
`downtime_event` and `production_record` rows and rejects a combined total
above 10,000 with `422`; it never truncates an OEE result. The public route
is rate-limited to 30 requests per minute per client.

## Non-goals

This document explains what OEE is and how it is computed, for readers who
don't read the domain code directly. It is **not** a specification for
other layers to reimplement:

- The OEE formula lives only in `src/paro/domain/oee.py`. No other layer
  (SQL, API, Power BI) computes or approximates Availability, Performance,
  Quality, or OEE.
- The SQL views in `docs/analytics.md` (`fact_downtime_event`,
  `fact_production_record`) expose raw facts only - durations, counts - never
  A/P/Q/OEE.

If this document and `src/paro/domain/oee.py` ever disagree, the code is
correct and this document is out of date.
