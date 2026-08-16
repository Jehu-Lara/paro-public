# PARO

Operational data platform for manufacturing: captures line downtime events and
production records, calculates **OEE** deterministically and auditably, and exposes an
analytics schema connectable to Power BI.

> **Status: Sprint 4 - Part B complete (analytics views for Power BI).** The OEE
> engine (Sprint 1), schema/migrations (Sprint 2), full HTTP API (Sprint 3), CI
> validation against real PostgreSQL (Sprint 4 - Part A), and the two analytics
> views `fact_downtime_event`/`fact_production_record` (Sprint 4 - Part B)
> already exist. See [MVP scope](#mvp-scope) and
> [Out of MVP scope](#out-of-mvp-scope).
>
> **Note on the database:** local development still runs on SQLite (the
> development environment doesn't have local Docker available). PostgreSQL
> is validated in CI via a `postgres:16` service in GitHub Actions, not local
> Docker; see
> [ADR 0002](docs/adr/0002-sqlite-temporary-due-to-virtualization-block.md) and
> [ADR 0003](docs/adr/0003-ci-postgres-service-without-local-docker.md).

---

## Live demo

API: <https://paro-public.onrender.com> · docs: <https://paro-public.onrender.com/docs>

> Runs on Render's free tier, which spins down after 15 minutes without
> traffic; the first request after idling can take ~30-60s to respond
> while the instance wakes up. There is no authentication on this demo —
> don't send anything sensitive to it, all data is synthetic.

---

## Problem

At many plants, machine downtime is logged in Excel **after** the shift. Micro-stops
get lost, OEE ends up overstated, and root-cause analysis is done on data nobody can
trace back to the original event.

## User

Continuous improvement, quality, and production engineers at manufacturing plants
(reference context: the industrial corridor of Nuevo Leon).

## Value proposition

PARO **is not a dashboard**. It's the service underneath one:

- Event capture with validation and **database-guaranteed idempotency**.
- Correct interval arithmetic: overlapping events **do not** double-count lost
  minutes; a downtime that spans shifts contributes only its portion to each window.
- **Deterministic OEE calculation with `Decimal`**, with explicit *warnings* when an
  input makes the result unreliable, instead of returning a misleading number.
- Traceability of the metric back to the events that produced it.
- Documented analytics schema for Power BI.

## MVP scope

- 5 endpoints: `GET /health`, `POST /api/v1/downtime-events`,
  `PATCH /api/v1/downtime-events/{id}`, `POST /api/v1/production-records`,
  `GET /api/v1/oee`.
- Pure OEE engine in Python, no infrastructure dependencies.
- PostgreSQL + SQLAlchemy 2 (sync) + Alembic.
- Two enriched SQL fact views for Power BI.
- Deterministic synthetic data with edge cases.
- Unit tests (domain) and integration tests. Target: real PostgreSQL, never SQLite;
  temporary exception documented in [ADR 0002](docs/adr/0002-sqlite-temporary-due-to-virtualization-block.md).

## Out of MVP scope

Deliberate decisions, documented in `docs/adr/`. Listed here so the project
**doesn't promise what it doesn't have**:

| Out of scope | Reason |
|---|---|
| `GET /losses/pareto` as a REST endpoint | The SQL view already serves the same data to Power BI |
| Physical date table | Power BI generates it with `CALENDARAUTO()` |
| AI/LLM, frontend, authentication, sensors, MES | Out of scope by design |

## Requirements

- Python **3.14** (uses the system interpreter; see `docs/adr/0001-python-314.md`)
- [uv](https://docs.astral.sh/uv/)

## Quick start

```bash
uv sync --extra dev
cp .env.example .env
uv run uvicorn paro.main:app --reload
```

Then: <http://127.0.0.1:8000/health> and <http://127.0.0.1:8000/docs>.

## Development commands

| Action | Command |
|---|---|
| Install dependencies | `uv sync --extra dev` |
| Tests | `uv run pytest` |
| Domain only | `uv run pytest tests/unit` |
| Domain coverage | `uv run pytest --cov=src/paro/domain --cov-report=term-missing` |
| Lint | `uv run ruff check src tests` |
| Format | `uv run ruff format src tests` |
| Types | `uv run mypy src` |
| Server | `uv run uvicorn paro.main:app --reload` |

## OEE formulas

```
Planned Production Time = window duration - union(planned downtimes ∩ window)
Run Time                = Planned Production Time - union(unplanned downtimes ∩ window)

Availability = Run Time / Planned Production Time
Performance  = (Ideal Cycle Time x Total Count) / Run Time
Quality      = Good Count / Total Count
OEE          = Availability x Performance x Quality
```

Vorne/oee.com format. Edge case detail (zero denominator, `Performance > 100%`,
open events) is documented in `docs/oee-definition.md`.

## Limitations

- Demo data is **synthetic** and marked as such.
- No authentication: the service is meant to run on an internal network.
  `POST`/`PATCH` write endpoints are excluded from CORS (browser JS on
  another origin can't call them); reads (`GET`) are open to any origin.
- Shifts are modeled as concrete instances, not recurrence rules.

## Roadmap

1. Sprint 1 - interval and OEE engine with tests.
2. Sprint 2 - persistence, migrations, and idempotency.
3. Sprint 3 - full API and integration tests.
4. Sprint 4 - analytics layer, CI, and documentation.

---

*Portfolio project. All included data is synthetic.*
