# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

- `GET /api/v1/oee`'s `Performance` component lost precision whenever a
  window had more than one `production_record` with different
  `ideal_cycle_time_seconds`: `routers/oee.py` computed a weighted average
  (`weighted_sum / total_count`, a division) and `domain/oee.py` multiplied
  it back by `total_count` to recover the aggregate ideal time. That
  divide-then-multiply round-trip is lossy whenever the average has no
  finite decimal representation - verified empirically with `Decimal(50) /
  Decimal(3) * 3 != Decimal(50)` (drifts by `1E-26` under the default
  context), and no increase in `Decimal` precision fixes it, since the
  quotient itself is already an approximation. Fixed at the root instead of
  patched: `calculate_oee`'s `ideal_cycle_time_seconds` parameter is now
  `ideal_time_total_seconds` - the aggregate ideal time, already summed
  exactly by the caller (`routers/oee.py::_ideal_time_total_seconds`, no
  longer named "weighted", no longer divides). The domain function never
  reconstructs an average; it consumes the exact sum directly. New
  regression test (`tests/integration/test_api_oee.py`) asserts the
  aggregation returns the exact literal sum for a case whose per-unit
  average is non-terminating, which the previous implementation could not
  have guaranteed.
- `production_record.ideal_cycle_time_seconds` now has a database-level
  `CHECK (ideal_cycle_time_seconds >= 0)` constraint (migration 0003), so a
  negative value is rejected regardless of the insertion path, not only
  when it goes through the HTTP API's Pydantic validation. On SQLite this
  required dropping and recreating the `fact_production_record` view around
  the batch table rebuild, since SQLite has no `ALTER TABLE ADD CONSTRAINT`
  and the view depends on the table; PostgreSQL adds the constraint directly
  without touching the table.
- `GET /api/v1/oee`: `OeeResult.warnings` is now typed as `list[Warning]`
  instead of `list[str]`, removing a `# type: ignore[arg-type]` at the API
  boundary (`api/routers/oee.py`). No behavior change: `Warning` is a
  `StrEnum`, so JSON serialization and equality against string values are
  unaffected.
- `GET /api/v1/oee` had a weaker tz-aware check (`tzinfo is None`) than
  `domain/intervals.py` (`tzinfo is None or tzinfo.utcoffset(moment) is
  None`), so a `tzinfo` present but unable to resolve a real offset would
  pass the router's check and raise an unhandled `ValueError` deep in the
  domain, turning into a 500 instead of a 422. `domain/intervals.py` now
  exposes `require_aware` (was private); the router delegates to it and
  converts `ValueError` into `HTTPException(422)`, instead of reimplementing
  a looser version of the same check.
- `README.md` no longer implies a Docker-based local setup that doesn't
  exist: there's no `Dockerfile` or `docker-compose.yml` in this repo, and
  PostgreSQL is only validated in CI (a `postgres:16` GitHub Actions service
  container, see ADR 0003) - local development runs on SQLite. Removed the
  "Docker Desktop" bullet from Requirements and "Docker" from the Sprint 4
  roadmap line, both of which overstated what's actually provided.
- `db/repositories.py::_is_unique_violation`'s SQLite fallback matched a
  UNIQUE violation by column names alone (`"source" in message`), and
  `downtime_event`/`production_record` share the same column names. A
  `production_record` violation could in theory be misattributed to
  `downtime_event` (or vice versa) if the wrong table's error text happened
  to satisfy the check. Verified empirically that SQLite's UNIQUE violation
  text never includes the constraint name (only `table.column`, unlike
  PostgreSQL's, which does and was already anchored correctly) - added a
  required `table_name` parameter and qualified each column check with it
  (`f"{table_name}.{name}"`).

### Changed

- `db/session.py`'s engine and `sessionmaker` were built as a module-level
  side effect (`engine: Engine = _make_engine()` at import time), coupling
  merely importing the module to `get_settings()` already being resolved
  and complicating anything that needs to swap the connection string.
  Replaced with `get_engine()`/`get_session_local()`, both cached
  (`lru_cache`, same pattern already used by `get_settings()` itself) so
  construction is deferred to first call instead of import, with identical
  singleton behavior otherwise. `api/deps.py::get_db` and
  `scripts/seed_demo.py::main` updated accordingly; `alembic/env.py` builds
  its own engine independently and needed no change. No test previously
  exercised the real `get_db()` (the `client` fixture always overrides it,
  and `test_seed_demo.py` never calls `main()`) - new
  `tests/integration/test_db_session.py` covers the real wiring end to end,
  plus that import alone no longer builds an engine and that the SQLite
  foreign-key PRAGMA still gets registered correctly. `conftest.py`'s
  docstring explaining why `get_settings.cache_clear()` is needed before
  running Alembic in tests referenced the old eager-import behavior; updated
  to describe the new lazy one.
