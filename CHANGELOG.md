# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

- `GET /api/v1/oee`: `OeeResult.warnings` is now typed as `list[Warning]`
  instead of `list[str]`, removing a `# type: ignore[arg-type]` at the API
  boundary (`api/routers/oee.py`). No behavior change: `Warning` is a
  `StrEnum`, so JSON serialization and equality against string values are
  unaffected.
