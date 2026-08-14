# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

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
