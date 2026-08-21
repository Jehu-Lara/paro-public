# ADR 0004 - Deterministic simulator and rolling demo feed

- **Status:** accepted
- **Decision date:** 2026-08-16
- **Reconciled:** 2026-08-20

## Context

PARO needs synthetic manufacturing facts that exercise the same validation,
idempotency, audit, and OEE paths as an external integration. The generator
must remain reproducible, while HTTP transport may run concurrently. A public
demo also needs recent data without pretending to be a sensor or MES feed.

## Decision

### Pure generator

`generate(config, seed, start, end)` is pure: no database, network, wall clock,
sleep, or shared random state. Machines are processed sequentially in stable ID
order. Each machine receives a SHA-256-derived RNG substream, so another
machine's output cannot change its sequence.

Production is aggregated into contiguous 15-minute line buckets. A line is a
serial process: its lowest-ID machine provides the deterministic bottleneck
cycle clock, and cycles overlapping a stop on any machine are excluded.
Component event hazards are divided across the line's machines and calibrated
with `SERIAL_LINE_EVENT_RATE_FACTOR`; this prevents four machine streams from
being mistaken for four parallel line capacities. Downtime stays at event
grain. The OEE formula remains exclusively in
`paro.domain.oee.calculate_oee`; the simulator produces inputs, never metrics.

### Deterministic identities

Every generated row has a time-based external ID. Production IDs contain line
and absolute UTC bucket start; downtime IDs contain machine, absolute UTC event
start, and deterministic sequence. Same inputs reproduce the same IDs and
payloads. Adjacent windows cannot reuse an ID for a different payload.

The rolling feed uses source `simulator-live-v1`, isolated from historical
backfills. Its daily seed is derived from master seed plus production date.

### Rolling driver

The Render cron runs every 15 minutes. It regenerates production days aligned
to 06:00 `America/Monterrey`, but publishes only completed buckets and events
whose start is already visible. An event that has started but not ended is
created open; a later run closes it through the existing PATCH endpoint and
optimistic concurrency. Catch-up is capped at 48 hours and reports older gaps.

Production-day boundaries are explicit simulator hand-offs. A generated event
drawn past 06:00 is closed at the boundary before the next day's deterministic
state begins.

### Transport, authentication, and transactions

Generation is sequential; HTTP writes use a bounded worker pool. Writes always
go through the API, never directly to persistence. `X-API-Key` authenticates;
the separate `X-Paro-Trusted-Ingest` token only exempts the cron from the
in-memory rate limit. Both comparisons use `secrets.compare_digest`.

Each HTTP request owns one database transaction and one commit. A multi-row run
is deliberately not atomic: failures are collected, the process exits nonzero,
and deterministic IDs make the next run safe. Database insertion order,
autoincrement IDs, and timestamps are not part of reproducibility.

### QA implementation

The implemented QA is deterministic code in `scripts/simulator/qa.py` and
`scripts/qa_simulator.py`. It checks smoke/idempotency behavior, database
constraints, and statistical acceptance bands against a disposable database.
No autonomous Developer Agent, LangGraph, Ollama, or model dependency is part
of the build or runtime.

## Alternatives rejected

- **One generator thread per machine:** shared scheduling would undermine
  reproducibility and provides no benefit for independent simulations.
- **Independent 15-minute generations:** resets machine state and previously
  reused relative external IDs across windows.
- **Direct database writes:** bypasses the public validation and audit path.
- **LangGraph/Ollama orchestration:** evaluated but unnecessary; deterministic
  tests provide the required gate without runtime or build-tool complexity.
- **Bulk ingestion:** still a possible future optimization, not required for
  the bounded trusted demo feed.

## Consequences

- Generated event streams are reproducible; database byte order is not.
- The synthetic topology is an explicit serial-line abstraction, not a claim
  about a specific plant layout.
- A partial batch can be visible, but retry is safe and the condition is never
  represented as atomic.
- The demo is live-updating every 15 minutes, not streaming or a production
  sensor/MES integration.
- Secret rotation and Render/Neon availability remain operational concerns.
