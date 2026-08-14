# ADR 0003 - Close ADR 0002's exit criterion with a Postgres service in GitHub Actions

- **Status:** resolved — implemented and verified on 2026-08-13, see
  "Resolution"
- **Date:** 2026-08-13

## Context

[ADR 0002](0002-sqlite-temporary-due-to-virtualization-block.md) temporarily
pivoted to SQLite for the schema/migrations/repositories (Sprint 2) and set
an explicit exit criterion: `tests/integration/` must run again, without
modifying the CHECK/UNIQUE/FK constraints it verifies, against real
PostgreSQL before declaring Sprint 2 closed for good.

Docker Desktop remains unavailable in the development environment (see ADR
0002's Context). That blocker is local to the environment; it hasn't been
resolved and is not part of this decision.

GitHub Actions runs on cloud-hosted runners, unrelated to the blocked
machine. `services: postgres` in a GitHub Actions workflow provides a real
Postgres without requiring local Docker Desktop — it's the only path that
allows closing ADR 0002's exit criterion while the local virtualization
blocker remains unresolved.

## Decision

Add a second job (`integration-postgres`) to
`.github/workflows/ci.yml`, alongside the existing `quality` job (lint/
format/mypy/pytest on SQLite, unchanged), with a `postgres:16` service and
fixed credentials for CI. That job runs `uv run pytest tests/integration -v`
against that service.

`tests/integration/conftest.py::migrated_engine` gains a conditional
branch: if the `PARO_TEST_POSTGRES_URL` environment variable exists (only
set in the new job, never in local development), it's used directly instead
of creating a temporary SQLite database. Since a single Postgres service is
shared across all tests in the job (unlike SQLite, which today gets a fresh
file per test), test isolation is achieved by running
`alembic downgrade base` + `alembic upgrade head` before each one, leaving
the schema clean. Without that environment variable, the current behavior
(temporary SQLite per test) doesn't change: the local development workflow
still doesn't depend on Postgres or Docker.

It's accepted upfront that `downgrade`+`upgrade` per test may end up slow
when sharing a single service — a faster alternative (e.g., a single
initial migration followed by `TRUNCATE ... CASCADE` between tests) is not
adopted from the start, so as not to solve a performance problem that
hasn't been measured yet. If the job turns out too slow in practice, the
cleanup strategy will be reconsidered as a later iteration, not as part of
this initial decision.

## Consequences

- Closes ADR 0002's exit criterion without needing local Docker Desktop:
  verification happens in the cloud.
- Local development doesn't change: it still runs on SQLite, zero
  dependency on Postgres to run the suite on the dev machine.
- Migration 002 (analytics views for Power BI) is out of scope for this
  ADR: its design is documented in `docs/analytics.md`, but its SQL
  implementation is deferred until the `integration-postgres` job is
  green — this avoids building on a schema that hasn't yet been
  revalidated against the real target engine.
- All items above were completed and are recorded in "Resolution" below.

## Resolution (2026-08-13)

The `integration-postgres` job was implemented, pushed, and ran green: 40
integration tests passing against real PostgreSQL 16 in a few seconds.
ADR 0002's Status was updated to resolved the same day. See ADR 0002's own
"Resolution" section for full detail, including a bug found and fixed by
this same job (`_is_unique_violation` cross-dialect detection).
