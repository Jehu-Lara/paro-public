# Downtime event corrections (design)

## Purpose

`POST /api/v1/downtime-events` records a downtime event once and is
idempotent by `(source, external_id)`, but has no way to fix a mistake
after the fact: a wrong `reason_id`, a typo'd `operator_note`, an event
that needs closing (`ended_at`). This document describes
`PATCH /api/v1/downtime-events/{id}`, the optimistic-concurrency mechanism
it uses, and the `audit_log` table it writes to.

## Optimistic concurrency: `expected_updated_at`

Every PATCH request must include `expected_updated_at`, the value of
`downtime_event.updated_at` the caller last read. The server compares it
against the row's current `updated_at`:

- **Match** -> the patch is applied (or is a no-op, see below).
- **Mismatch** -> `StaleUpdateError` -> HTTP 409. Someone else updated the
  row between the caller's read and this request; the caller should re-fetch
  and retry rather than blindly overwrite.

**Alternative considered and rejected:** a dedicated integer `version`
column, incremented on every update (the more common pattern for optimistic
locking). `updated_at` was reused instead because it already exists on
`DowntimeEvent` with `onupdate=_now_utc` wired (see `db/models.py`) — adding
`version` would mean two columns tracking "has this row changed," with no
behavioral difference between them. If sub-second PATCH collisions on the
same row ever become common enough that timestamp resolution stops being a
safe token, revisit this.

## `audit_log`

One row per PATCH that **actually changes** something. Resubmitting the
same values you already see is a no-op — same idempotent philosophy as the
`POST` endpoints' `(source, external_id)` handling — and writes no row.

| Column | Meaning |
|---|---|
| `id` | Primary key. |
| `downtime_event_id` | FK to the corrected row. |
| `changed_fields` | `{field: [old, new]}`, only the fields that actually differed from the request. |
| `actor` | Free-text, nullable. See below. |
| `changed_at` | UTC timestamp of the correction. |

Scoped to `downtime_event` corrections only — not a generic, polymorphic
audit table for arbitrary entities. If `production_record` or any other
resource later grows its own `PATCH`, extend this design deliberately
rather than assuming this table already covers it.

**`actor` is not a verified identity.** Real authentication is a separate,
explicitly out-of-scope item (see `README.md`'s "Out of MVP scope"). Until
that exists, `actor` is a free-text field the caller supplies in the PATCH
body — the same trust level as `downtime_event.operator_note`. Don't build
authorization logic on top of it.

## No `GET` endpoint over `audit_log`

Same treatment as the two analytics fact views (`docs/analytics.md`):
`audit_log` is a table, not a new REST surface. Query it directly against
Neon, or add it to the Power BI model, if you need to browse it.
