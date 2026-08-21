# Known issues

Lightweight, dated, append-only list of incidental bugs found during
development -- not architectural decisions (those go in `docs/adr/`) and
not product-facing limitations (those go in `README.md`'s "Limitations"
section). One entry per item: what it is, where it surfaced, why it's
non-blocking, and what would resolve it.

## `GET /health` bypasses `Depends(get_db)`, colliding with `get_session_local()`'s process-wide cache on Windows

- **Status:** resolved 2026-08-20.

- **Discovered:** 2026-08-19, while adding `tests/integration/test_api_auth.py`.
- **What:** `GET /health` (`src/paro/main.py`) calls `get_session_local()()`
  directly instead of going through the `Depends(get_db)` dependency every
  other endpoint uses. `get_session_local()` is `@lru_cache(maxsize=1)`
  (`src/paro/db/session.py`) -- process-wide, one instance for the whole
  test run.
- **Where it surfaces:** an integration test that calls `client.get("/health")`
  against a real `migrated_engine`-backed temporary SQLite file leaves a
  connection open past that test's teardown, because the cached
  `SessionLocal` outlives the fixture that created the temp file. On
  Windows, `tempfile.TemporaryDirectory` cleanup then fails with
  `PermissionError: [WinError 32]` (file still in use by another
  process) -- the stale handle held by the cached engine. This was hit
  directly: the original draft of `test_api_auth.py` included a
  `GET /health` read-stays-open test, which triggered exactly this
  failure; it was swapped for an equivalent `GET /oee` test (which does
  go through `Depends(get_db)`) instead of being deleted outright.
- **Why non-blocking:** `/health` already catches `SQLAlchemyError`
  internally and returns 200 even against an unreachable or wrong
  database, so its own test coverage
  (`tests/unit/test_health.py`) never touches `migrated_engine` and never
  triggers this. No integration test other than the original draft above
  has ever exercised `/health` against a real temp-file-backed engine.
  Production deployments (Render + Neon, a long-lived connection, not a
  per-test temp file that gets deleted) aren't affected by this failure
  mode at all -- it's specific to test teardown on Windows.
- **Resolution:** `GET /health` now accepts `db: Session = Depends(get_db)`
  like every other endpoint. A migrated-database integration test covers the
  reachable case; a separate `/ready` endpoint returns 503 for dependency
  failure while `/health` preserves its liveness-only 200 contract.
