# ADR 0004 - Advanced Industrial Simulator built via a Multi-Agent System

- **Status:** proposed
- **Date:** 2026-08-16

## Revision (2026-08-16)

Still status "proposed" (no simulator code exists yet), amended in place
rather than superseded by a new ADR. Verifying the actual schema, API
validators, and analytics views before any code was written (see the
implementation notes accompanying this revision) surfaced that the original
**"one thread per machine"** concurrency model contradicts reproducibility
and buys nothing here — see "Simulator architecture" below for the
replacement (sequential generation with per-machine RNG substreams,
concurrent HTTP transport) and the reasoning. This revision also adds the
core/driver logical-clock design and softens the "inherits validation for
free" consequence. The write-rate arithmetic, RNG-substream mechanics, and
the two-tier QA check design surfaced by that same verification belong in
an implementation spec, not this ADR — see the accompanying report for why
that spec isn't written yet.

## Revision (2026-08-18)

Still status "proposed". Amended in place again, same pattern as the
2026-08-16 revision above. The "MAS team" section below describes a
Developer Agent that iteratively writes and revises the simulator's
source, gated by a QA Agent, because at the time this ADR was written no
human was going to hand-write the simulator. That premise stopped being
true during Steps 3-4 (commits ab6677f, 283770c, 27d1591, 9476294):
scripts/simulator/generator.py, client.py, transport.py, and
scripts/simulate_production.py were all written and reviewed by hand,
not by an autonomous Developer Agent. By the time Step 5 was reached,
there was no more code-generation task left for a Developer Agent to
gate, and no round-tripping loop to build.

**Step 5, as actually built: QA Agent checks only — no Developer Agent,
no LangGraph, no Ollama.** scripts/simulator/qa.py and
scripts/qa_simulator.py implement simulator-spec.md section 7's
SMOKE/IDEMPOTENCY checks and section 8's ACCEPTANCE statistical bands,
run against a real disposable database through the already-built
generate()/transport() pipeline. The "Tech stack for orchestration"
section below (LangGraph selection, Ollama) was never implemented and is
no longer planned — the concern that motivated ruling those dependencies
out of the runtime dependency list is moot, since neither was ever added.
Left in place below as a record of the evaluation that was done, not as
a description of what was built.

## Context

The PARO backend MVP (schema, repositories, API, analytics views, Power BI
dashboard) is complete. Phase 2 needs a data source that behaves like a real
production line — not the deterministic, single-shot rows `scripts/seed_demo.py`
produces — so the dashboard and API can be exercised under realistic,
continuous load: normal cycles, micro-stops, machine failures, cycle-time
variation, and scrap, injected concurrently across lines and machines over
time rather than as one fixed batch.

Building that simulator (the scripts that generate this data and write it
through the API/DB) is itself a nontrivial, multi-file effort with two
distinct concerns that benefit from separation: writing the simulation logic,
and verifying that what it writes actually respects the schema's constraints
and the analytics views' assumptions (documented in `docs/analytics.md`).
Rather than writing and self-reviewing that code as one task, this ADR
proposes structuring the build itself as a Multi-Agent System (MAS): a
Developer agent that writes the simulator, and a QA agent that tests it
against the database and enforces corrections, iterating without a human in
the loop for each round.

This ADR is scoped to the **architecture of the simulator and of the agent
team that builds it** — not to the simulator's implementation. No simulator
source code is written as part of this decision.

## Decision

### Simulator architecture

- **Logical clock — core generator vs. live driver (supersedes nothing,
  resolves a tension in Context above):** the simulator core is a pure
  generator: `(config, seed, start, end) -> events`, where each event carries
  a *virtual* timestamp. No sleeps, no I/O, no network inside the core — 14
  simulated days across 8 machines generates in seconds. This is what makes
  the QA Agent's 5-round cap viable at all against a multi-day acceptance
  run.

  Context (above) describes "continuous load... over time," which reads like
  a live, real-time feed. That's not a second architecture — it's a thin
  *driver* over the same core: an optional live mode maps virtual time to
  wall-clock time with a speed factor (e.g. `--speed 60` => 1 real minute =
  1 simulated hour) and sleeps there, outside the core. The core's boundary
  is drawn so adding that driver later needs zero core changes. Backfill
  (generate 14 days of virtual timestamps in the past, transport them now) is
  the *general* case this core supports directly; live mode is a later,
  optional wrapper, not the starting point.

- **Concurrency model — supersedes the original "one thread per machine"
  design (see Revision, above):** a shared-RNG, multi-threaded generator is
  not reproducible — with threads sharing an RNG, scheduler interleaving
  decides which draw each machine receives, and interleaving isn't
  deterministic. Threads also model contention that doesn't exist here: in
  this spec, machines are fully independent — none consumes another's
  output. Replaced with two separate concerns:
  - **Generation:** sequential per machine, each machine driven by its own
    RNG substream derived deterministically from the master seed, so
    machine *N*'s output never depends on what any other machine generated.
    This also means a single machine's output can be regenerated in
    isolation for debugging, without replaying the rest.
  - **Transport:** concurrent HTTP writes via a bounded worker pool over
    already-generated batches, through the existing API client (not direct
    DB writes, so the simulator exercises the same validation path real
    integrations would use). Concurrency belongs at this layer, where it's
    actually needed (network latency) and is safe because `external_id` is
    deterministic per event — arrival order at the API cannot change the
    result.

  **Determinism applies to the generated event stream, not to the
  database:** same seed + same config yields the same canonical sequence of
  generated events (same order, same values) — verifiable by hashing a
  canonical dump of the generator's output *before* transport. Because
  transport is concurrent, DB insertion order, autoincrement ids, and
  `created_at` legitimately vary run to run even with an identical seed; the
  database is verified by row counts and invariants, never by byte-for-byte
  equality against a prior run.

- **Statistical noise injection:** cycle times drawn from a distribution
  centered on each machine's `ideal_cycle_time_seconds` (e.g. a truncated
  normal, to avoid negative cycles) rather than a fixed value; micro-stops
  and failures triggered by independent Bernoulli draws per cycle, with
  duration drawn from separate distributions per `downtime_reason` (short,
  high-frequency for micro-stops; long, low-frequency for failures); scrap
  modeled as a per-cycle Bernoulli draw feeding `total_count` vs.
  `good_count`.
- **Idempotency:** reuses the `source` + `external_id` idempotent-write
  convention already established in `paro.db.repositories` and used by
  `scripts/seed_demo.py`, so a crashed and restarted simulator run doesn't
  double-write.

### The MAS team

Two agents, each with a narrow, single-purpose role:

- **Developer Agent** — writes and revises the simulator's source
  (`scripts/simulate_production.py` and any supporting modules), scoped
  strictly to that code. Does not decide whether its own output is correct.
- **QA Agent** — never writes simulator code. Given the Developer Agent's
  current output, it runs the simulator against a disposable database,
  and checks: the process completes without raising, every written row
  satisfies the schema's CHECK/UNIQUE/FK constraints (the same set
  `tests/integration` verifies), and the resulting data is statistically
  plausible (e.g. failure/micro-stop/scrap rates land within the configured
  target ranges, not all-zero or saturated). It reports a structured
  pass/fail plus concrete findings — not prose feedback — back to the
  Developer Agent.

Both agents operate against a single shared specification (this ADR, plus
the target distributions/rates configured for a given run) — neither agent
invents requirements the other didn't agree to.

### Auto-validation flow

1. Developer Agent produces or revises the simulator script.
2. QA Agent runs it against a disposable Postgres database (same
   `services: postgres` pattern the `integration-postgres` CI job already
   uses — see ADR 0003), captures constraint violations, exceptions, and
   distributional checks.
3. If QA Agent finds no issues, the round ends and the script is accepted.
4. If QA Agent finds issues, it returns them as structured findings (file,
   the specific check that failed, expected vs. observed) to the Developer
   Agent, which revises and resubmits. This repeats without a human up to a
   fixed round cap (e.g. 5); hitting the cap without a pass escalates to a
   human rather than looping indefinitely or silently accepting a failing
   script.
5. Every round's findings and diffs are logged, so a human reviewing the
   final accepted script can see the corrections the QA Agent enforced along
   the way, not just the end state.

The QA Agent is the sole gate: the Developer Agent's own claim that its code
is correct never ends a round by itself.

### Tech stack for orchestration

Evaluated three frameworks for coordinating the two-agent loop above:

- **LangGraph** — models the Developer↔QA exchange as an explicit graph with
  typed state passed between nodes and native conditional edges (exactly the
  "pass → end, fail → loop back with findings" control flow this ADR needs).
  More setup than a plain agent-loop library, but the explicit graph is
  easier to reason about and log than an implicit conversation, and it has
  no required hosted-service dependency — it runs fully local against any
  OpenAI-compatible endpoint, including Ollama.
- **CrewAI** — optimized for a crew of agents each with a distinct persona
  collaborating on one shared task/output; a good fit for role-based teams,
  but its "crew" abstraction is loosely typed and less suited to a strict
  gated pass/fail loop with a hard round cap than LangGraph's explicit graph
  edges.
- **AutoGen** — strong at open-ended multi-turn agent conversation, but
  that's a mismatch here: this flow needs bounded, structured
  request/response rounds with a hard stop condition, not an open-ended
  conversation the framework has to be constrained out of.

**Selected: LangGraph.** The Developer↔QA cycle is a small, well-defined
graph (write → test → branch on pass/fail → loop or end) rather than an
open-ended conversation, which is what LangGraph is built to express
directly. It also runs against local models via Ollama with no code
different from a hosted model, keeping the simulator-building step
reproducible without a paid API dependency — relevant since this MAS is a
one-time build tool, not a production runtime component.

## Consequences

- No simulator source code exists yet; this ADR only fixes the architecture
  and the agent team's division of responsibility. Implementation is a
  separate, later task.
- The QA Agent's checks (constraint validity + distributional plausibility)
  need to be defined precisely enough to be machine-checkable before the
  Developer Agent can be run against them — that concrete spec (clock
  model, determinism contract, RNG substreams, statistical parameters,
  rate-limit strategy, two-tier check design) is not fixed by this ADR; see
  [`docs/simulator-spec.md`](../simulator-spec.md), which must be reviewed
  and confirmed before implementation starts. A batch/bulk ingest endpoint
  (`POST /downtime-events/batch` or similar) was identified there as the
  correct long-term fix for write-volume/rate-limit pressure on real
  ingestion, not just the simulator — named as a **deferred** future option,
  not built as part of this work.
- Choosing LangGraph ties the build tooling to that library and, if used,
  an Ollama-served local model; neither is a runtime dependency of the PARO
  backend or API — this is tooling used once to produce the simulator
  script, not a component the deployed service depends on.
- The simulator itself writes through the existing API client, so
  inheriting the API's validation cuts both ways: it inherits any *future*
  validation change for free with no dedicated simulator-side compatibility
  layer, but it also inherits *today's* validations exactly as they stand —
  which were never written with a 14-day backfill in mind, since nothing in
  the schema or API previously needed to reject or accept old timestamps on
  purpose (see the verification notes on this ADR's revision). A validation
  rule added later specifically to reject old data would block the
  simulator too, not just real integrations.
