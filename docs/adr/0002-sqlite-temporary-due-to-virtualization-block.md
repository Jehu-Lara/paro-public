# ADR 0002 - Temporary SQLite as a persistence pivot (Sprint 2a)

- **Status:** resolved — exit criterion met on 2026-08-13, see "Resolution"
- **Date:** 2026-08-12
- **Expires:** N/A (resolved)

## Context

Sprint 2 requires PostgreSQL + SQLAlchemy + Alembic. In the development
environment, Docker Desktop is not available: the host's virtualization
support is blocked by an unresolved, environment-specific issue unrelated to
this project's design.

This is a fact of the environment, not a problem to solve in TAREA 003: WSL,
Podman, native Postgres for Windows, and cloud-hosted databases were not, and
will not be, evaluated as alternatives within this task.

## Decision

Temporarily pivot to SQLite (`./paro.db`, local file) to move forward with
the schema, migrations, and integration tests for Sprint 2, and return to
PostgreSQL as soon as the development environment allows it.

The design criterion is that migrating back should be **only a connection
string change** (`PARO_DATABASE_URL`). For that to be true in practice, not
just in words, four mitigations are applied:

1. **`UTCDateTime` (`src/paro/db/types.py`).** SQLite has no timezone-aware
   date/time type: reading one returns a naive `datetime`. The domain
   (`domain/intervals.py`) rejects any naive value with `ValueError`. This
   `TypeDecorator` normalizes to UTC on write and reassigns `tzinfo=UTC` on
   read, so the ORM and domain never see a naive value on either dialect.

2. **`PRAGMA foreign_keys=ON` (`src/paro/db/session.py`).** SQLite does not
   enforce foreign keys by default. Without the listener on the `connect`
   event, an invalid `machine_id` gets inserted silently and no test catches
   it until running against PostgreSQL, which always enforces them. The
   listener only acts when the connection is `sqlite3.Connection`.

3. **`render_as_batch=True` conditioned on dialect (`alembic/env.py`).**
   SQLite does not support `ALTER TABLE` for most schema changes; Alembic
   works around it by recreating the table ("batch mode"). Enabling it
   always would generate migrations different from the ones that would run
   on PostgreSQL, so it's only enabled when
   `connectable.dialect.name == "sqlite"`.

4. **No dialect-specific types or SQL.** No `JSONB`, `ARRAY`, `EXCLUDE`, nor
   `server_default` with engine functions. `created_at` / `updated_at` use a
   Python default/`onupdate` (`datetime.now(UTC)`), not `server_default`, so
   behavior is identical on both dialects instead of depending on each
   engine evaluating its own server-time function.

## Known limits (accepted for S2a, not for Sprint 2's close)

- **SQLite's loose typing.** SQLite does not enforce column types with the
  same strictness as PostgreSQL (type affinity, not real type enforcement);
  a value of the wrong type can get in without error where PostgreSQL would
  reject it.
- **Single-writer lock.** SQLite serializes writes at the whole-database
  level; it does not reproduce PostgreSQL's concurrency behavior (MVCC,
  row-level locks). No test in this suite can be used as evidence that the
  schema behaves well under concurrent writes.
- **No `JSONB`, `ARRAY`, or `EXCLUDE`.** By design (mitigation 4): if some
  future sprint needs them, that decision will need to be revisited
  separately.

## Exit criterion

This integration test suite (`tests/integration/`) must run again, without
modifying the CHECK/UNIQUE/FK constraints it verifies, against real
PostgreSQL — **before** declaring Sprint 2 closed for good. Changing
`PARO_DATABASE_URL` to `postgresql+psycopg://...` should be, by design, the
only change required.

## Consequences

- Sprint 2a (this one) delivers schema + migration 0001 + real integration
  tests, but on SQLite.
- Formally closing "Sprint 2 complete" was made contingent on the
  revalidation against PostgreSQL described above, met in the Resolution.
- `psycopg[binary]` stays in `pyproject.toml` even though it isn't used yet
  in S2a: PostgreSQL remains the target, not a discarded option.

## Resolution (2026-08-13)

The local virtualization blocker (Context) remains unresolved in the
development environment; resolving it turned out not to be necessary. The
exit criterion was met via ADR 0003's alternative path: a `postgres:16`
service in GitHub Actions, not local Docker Desktop. `tests/integration/`
ran without modifying any CHECK/UNIQUE/FK, as the original exit criterion
required.

- **Job:** `integration-postgres`. Result: green, 40 integration tests
  passing against real PostgreSQL 16 in a few seconds.
- **One earlier CI attempt failed first:** 10 of 40 idempotency tests
  returned an unhandled `IntegrityError` instead of the expected 200/409.
  This was not a problem with this ADR or with the CI job itself — it was a
  real, pre-existing bug in
  `src/paro/db/repositories.py::_is_unique_violation` (introduced in S2b):
  it recognized SQLite's error text (`"UNIQUE constraint failed"`) but never
  psycopg/PostgreSQL's (`"duplicate key value violates unique constraint"`),
  so the idempotency logic never activated outside SQLite. Fixed by
  anchoring detection to the constraint name (dialect-stable via
  `NAMING_CONVENTION`, `src/paro/db/base.py`) instead of the driver's error
  text. This bug is exactly the kind of SQLite/PostgreSQL divergence this
  ADR flagged as an accepted risk for S2a-S3; the exit criterion served its
  purpose by exposing it.
- **Known limits (section above), reassessed:** "SQLite's loose typing" and
  "Single-writer lock" remain true for local development on SQLite (the
  pivot doesn't disappear, see the default `PARO_DATABASE_URL` in
  `.env.example`), but they no longer apply to the set of guarantees
  validated in CI, which now runs against real PostgreSQL.
