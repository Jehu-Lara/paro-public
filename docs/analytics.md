# Analytics schema for Power BI (design)

**Status: implemented (migration 002,
`alembic/versions/0002_analytics_views.py`).** This document describes the
two enriched SQL fact views the README promises (`## MVP scope`), delivered
once the CI job against real PostgreSQL went green (see
[ADR 0003](adr/0003-ci-postgres-service-without-local-docker.md)).

## Non-negotiable design rule

The OEE formula lives **only** in Python. SQL views expose facts, not
business metrics: no view in this schema reimplements Availability,
Performance, Quality, or OEE.

No column in any view described here is a business ratio, percentage, or
formula (Availability, Performance, Quality, OEE). Every column listed
below is explicitly marked as a **raw fact** (a value that comes straight
from a column) or a **simple arithmetic derived value** (a subtraction or
timestamp/count difference, never a division). Availability, Performance,
Quality, and OEE keep living exclusively in `domain/oee.calculate_oee`,
exposed today by `GET /api/v1/oee`
([oee.py](../src/paro/api/routers/oee.py)) — Power BI consumes them from
there or recomputes them on the report side from these facts, never from a
view.

## View 1: `fact_downtime_event`

Grain: **one row per `downtime_event`**. Enriched with the dimensions Power
BI would otherwise need to resolve with repeated joins if they weren't here.

| Column | Source | Type |
|---|---|---|
| `downtime_event_id` | `downtime_event.id` | raw fact |
| `line_id`, `line_code`, `line_name` | `production_line` | raw fact |
| `machine_id`, `machine_code`, `machine_name` | `machine` (nullable: the event may have no machine) | raw fact |
| `reason_id`, `reason_code`, `reason_name` | `downtime_reason` | raw fact |
| `started_at`, `ended_at` | `downtime_event` (UTC; `ended_at` null if the event is still open) | raw fact |
| `is_planned` | `downtime_event.is_planned` | raw fact |
| `duration_seconds` | `ended_at - started_at` | simple arithmetic derived value; **NULL if `ended_at` is NULL** |
| `operator_note`, `source`, `external_id` | `downtime_event` | raw fact |
| `created_at`, `updated_at` | `downtime_event` | raw fact |

**Why `duration_seconds` can be NULL:** an open event doesn't have a fixed
duration until it closes. Closing it with an arbitrary `as_of` (e.g.
`NOW()`) would make the view return a different number every time it's
queried — not reproducible, and it's also exactly the decision
`calculate_oee` already makes explicitly with its `as_of` parameter (see
`domain/oee.py`). A SQL view shouldn't make that decision on its own.

## View 2: `fact_production_record`

Grain: **one row per `production_record`**.

The current Power BI semantic model deliberately imports the raw
`production_record` table for its historical report contract; the enriched
`fact_production_record` view below remains the documented analytics schema
for new consumers.

| Column | Source | Type |
|---|---|---|
| `production_record_id` | `production_record.id` | raw fact |
| `line_id`, `line_code`, `line_name` | `production_line` | raw fact |
| `interval_start`, `interval_end` | `production_record` (UTC) | raw fact |
| `interval_duration_seconds` | `interval_end - interval_start` | simple arithmetic derived value |
| `total_count`, `good_count` | `production_record` | raw fact |
| `rejected_count` | `total_count - good_count` | simple arithmetic derived value — **subtraction, not a ratio**; same computation already used by `ProductionRecordResponse.rejected_count` in the API ([production.py](../src/paro/api/schemas/production.py)), one definition reused by name, not reinvented here |
| `ideal_cycle_time_seconds` | `production_record` | raw fact (`Numeric`, never `float`) |
| `source`, `external_id` | `production_record` | raw fact |
| `created_at`, `updated_at` | `production_record` | raw fact |

**Why there's no `quality`, `performance`, or `oee` in this view:** the
view's grain is one row per `production_record`, and none of the three
components can be computed at that grain. `Quality` in `GET /api/v1/oee`
([oee.py](../src/paro/api/routers/oee.py)) is a **per-window
aggregation** — it sums `total_count`/`good_count` only across records
fully contained in `[start, end)`; a partially overlapping record is
excluded whole and flagged with the `PARTIAL_PRODUCTION_EXCLUDED` warning
(see `docs/oee-definition.md`) rather than silently dropped — not the
value of a single row.
`Availability`/`Performance` also require the planned/unplanned downtimes
for that same window, clipped and combined (`union`/`subtract` in
`domain/intervals.py`), which likewise don't exist at the level of a single
`production_record` row. Reimplementing any of the three in SQL — at this
grain or any other — is exactly what the rule above forbids.
`good_count`/`total_count` are left raw so Power BI can build its own
presentation ratio if it needs one, knowing it isn't the same `Quality`
returned by `GET /api/v1/oee` (that one aggregates per window; a ratio
computed directly in Power BI over these two single-row columns is not).

## Time zone

All timestamps in both views are UTC (`UTCDateTime` in the schema, see
`db/types.py`). `production_line.timezone` is available in both views via
the join to `production_line` so Power BI can convert to local plant time
in the report, not in the view.

## Out of scope for this document

- Any physical date table — the README already documents that Power BI
  generates it with `CALENDARAUTO()`.
- `GET /losses/pareto` as a REST endpoint — the README already documents
  that these views are what serve that data to Power BI directly.
