# Advanced Industrial Simulator — implementation spec

## Parámetros estadísticos (única fuente de verdad)

- **Versión:** 2
- **Fecha:** 2026-08-16
- **Micro-stop:** Bernoulli p = 0.030 por ciclo. Duración lognormal, mediana 60s
  (μ = ln(60) ≈ 4.0943, σ ≈ 0.5552 — verificado: exp(μ+σ²/2) ≈ 70.0s).
- **Failure:** Bernoulli p = 0.0018 por ciclo. Duración lognormal, mediana 1500s
  (μ = ln(1500) ≈ 7.3132, σ ≈ 0.7028 — verificado: exp(μ+σ²/2) ≈ 1920.3s).

Cualquier valor de estos dos parámetros citado en el chat de esta conversación
que no coincida exactamente con este bloque se considera inválido — incluida
la variante 10%/1% con duraciones uniformes "30-120s"/"15-60min" mencionada en
un mensaje posterior, que queda descartada. Este bloque es la referencia; el
resto del documento (y la reconstrucción del chat) no lo son.

**Status: draft.** Companion to [ADR 0004](adr/0004-simulator-multi-agent-architecture.md),
which fixes the simulator's architecture and the Developer/QA agent team that
builds it. This document fixes the *numbers and mechanics* that architecture
needs before either agent writes a line of code: the clock model, the
determinism contract, the RNG scheme, the statistical model, persistence
granularity, the rate-limit strategy, and the QA Agent's check tiers.

No simulator code, agent code, or limiter code exists yet. This is the
contract both agents read before either one runs.

## Provenance note

All statistical parameters are confirmed — see the source-of-truth block
above for micro-stop/failure, and section 4 for the rest (cycle time, scrap,
planned changeover, the deliberate ground-truth signals, and the reason
mix), all stated directly by you in this conversation, not proposed
defaults. Everything else in this document is verified directly against the
current codebase (validators, constraints, the rate limiter, `slowapi`'s
installed version) or derived arithmetic shown in place. Nothing in this
document is a placeholder as of this revision.

**`ideal_cycle_time_seconds` source — resolved.** `Machine`
(`src/paro/db/models.py:61-70`) has no cycle-time column; the field lives
only on `production_record`, per-record. Resolved as **simulator-config
only**: each machine's target cycle time is a value the simulator's own
config assigns (never persisted to `Machine`, never read back from prior
`production_record` rows — the latter fails outright for any machine with
no history, i.e. every machine on a fresh DB), written into each
`production_record` the simulator creates exactly as a real integration
would supply it. No schema change, no migration. No consequence for the
analytics views or `GET /api/v1/oee`: both already consume
`ideal_cycle_time_seconds` per-record exactly as today; a simulator-internal
config value feeding that same field changes nothing downstream.

## 1. Clock model

The simulator core is a pure function:

```
generate(config, seed, start, end) -> Iterable[Event]
```

Each `Event` (a not-yet-persisted production cycle, micro-stop, failure, or
scrap outcome) carries a **virtual timestamp** — a point on the simulated
line's own clock, independent of when the generator actually runs. The core
contains no `sleep`, no network I/O, and no database access. This is what
makes 14 simulated days across 8 machines generate in seconds rather than
in 14 real days, and it's what makes the QA Agent's round cap (see
[ADR 0004](adr/0004-simulator-multi-agent-architecture.md)) viable against a
multi-day acceptance run at all.

**Backfill is the general case, not a special case.** `start`/`end` can be
any window, including one entirely in the past — nothing about the core
cares whether `end` is before or after "now." The 14-day acceptance run is
just `generate(config, seed, now - 14d, now)`.

**Live mode is explicitly out of scope for this spec, but designed for.** A
future thin *driver* wraps the same core: it maps virtual time to wall-clock
time with a speed factor (`--speed 60` => 1 real minute = 1 simulated hour)
and sleeps *outside* the core, transporting each event's write near its
mapped wall-clock moment. Adding this driver later must require zero changes
to `generate()` — if it ever does, the core/driver boundary was drawn in the
wrong place.

## 2. Determinism contract

**Determinism applies to the generated event stream, not to the database.**
Same `seed` + same `config` over the same `[start, end)` window yields the
same canonical sequence of generated events — same order, same values,
every field. This is verified by hashing a canonical dump (e.g. newline-
delimited JSON, one line per event, in generation order) of the generator's
output **before transport**, and comparing that hash across runs.

The database is never verified this way. Transport is concurrent (section
3), so DB insertion order, autoincrement `id` values, and `created_at`
legitimately differ between two runs of the identical seed and config. The
database is verified by **row counts and invariants** (section 7) — never
by byte-for-byte or row-for-row equality against a prior run's database
state.

**Say this explicitly so the QA Agent doesn't fail a run over it:** a QA
check that compares database rows across two runs and finds different
`id`/`created_at` values, or different row *order*, is not looking at a bug.
The only cross-run comparison that's meaningful is the pre-transport event
stream hash.

**Implementation note (Step 3): dataclass equality, not a canonical-dump
hash, is what actually verifies this today.** The paragraphs above describe
hashing a canonical dump of the generated event stream as the verification
mechanism. `scripts/simulator/generator.py`'s own tests
(`tests/unit/test_simulator_generator.py::test_generation_is_deterministic_for_the_same_seed`)
instead call `generate()` twice with the same seed/config and assert the
two returned `GeneratedRun` values are equal — direct `==` on two
`@dataclass(frozen=True)` instances, which recursively compares every
field of every `ProductionRecordDraft` and `DowntimeEventDraft` in both
sorted tuples. This is at least as strong as the hash comparison for what
it actually checks (same order, same values, every field — this
contract's own wording), since dataclass equality can't collide the way a
hash theoretically could, and it needs no extra utility code to exist. It
does not, however, replace the hash for every future purpose: a hash is
still the right tool once the QA Agent (Step 5) needs to compare two runs
*without* holding both complete `GeneratedRun`s in memory at once — e.g.
comparing a run against a previously-recorded fingerprint from disk, or
across process boundaries, at the acceptance run's scale (10k+ rows).
Building that canonical-dump-and-hash utility remains out of scope for
Step 3, exactly as scoped in
[ADR 0004](adr/0004-simulator-multi-agent-architecture.md)'s Step 5 QA-Agent
work — this note only documents which mechanism Step 3 itself relies on,
and why it's sufficient for Step 3's own tests without yet building the
hash path.

## 3. RNG substreams

One `random.Random` instance per simulated machine, seeded deterministically
from a single `MASTER_SEED`:

```python
import hashlib

def machine_seed(master_seed: int, machine_id: int) -> int:
    digest = hashlib.sha256(f"{master_seed}:{machine_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")

machine_rng = random.Random(machine_seed(MASTER_SEED, machine.id))
```

SHA-256 over `f"{master_seed}:{machine_id}"`, first 8 bytes as a big-endian
int, is the chosen derivation. `random.Random(a)` doesn't accept a tuple
seed directly (raises `TypeError` — checked against the stdlib's accepted
seed types: `int`, `str`, `bytes`/`bytearray`, or `None`), so the string
join + hash gives a well-defined, order-independent way to turn
`(master_seed, machine_id)` into a valid seed.

**This derivation must not change silently once adopted.** Changing the hash
function, the string format, or the byte slice changes every previously
generated dataset's values for the same `(seed, machine_id)` pair — anyone
relying on a seed to reproduce a prior run would get silently different
data. If it ever needs to change, that's a spec revision, documented as such.

**Generation order:** sequential per machine, in a fixed machine order (by
`machine.id` ascending). Machine *N*'s output depends only on its own
substream — never on what any other machine generated, and never on wall-
clock scheduling (see [ADR 0004](adr/0004-simulator-multi-agent-architecture.md)'s
superseded "one thread per machine" decision). This also means a single
machine can be regenerated in isolation — same seed, same machine, same
window — without replaying the other seven, which is the actual debugging
benefit: reproduce one machine's anomalous output without waiting for a
full acceptance run.

## 4. Statistical model

### 4.0 Rate model — per run-hour, not fixed per-cycle probability

**This replaces the original formulation and supersedes it, for a specific
reason.** A fixed Bernoulli probability *per cycle*, applied regardless of
cycle time, makes the failure/micro-stop hazard scale with cycle *count*
rather than with running *time* — a machine with `T=5.5s` gets modeled as
failing ~5.5× more often per hour than one with `T=30s`, purely from the
per-cycle framing, which is backwards for most failure modes (mechanical,
electrical, and pneumatic failures track running time, not throughput).
Worse, because `ideal_cycle_time_seconds` has no canonical value anywhere in
this codebase (see the provenance note above), Availability would have
silently depended on whichever unverified `T` the simulator happened to
assume — exactly the failure mode this spec exists to prevent.

**Fix:** express the hazard as a rate **per hour of Run Time**
(`λ_MICRO_STOP_PER_RUN_HOUR`, `λ_FAILURE_PER_RUN_HOUR`), and derive the
per-cycle probability from `T` at runtime:

```
p_per_cycle = λ_per_run_hour × mean_cycle_seconds(T) / 3600
```

The rates are calibrated so that at the reference `T = 30s`, this
reproduces the source-of-truth block's per-cycle values exactly:

- `λ_MICRO_STOP_PER_RUN_HOUR = 3.2432` (→ `p = 0.030` at T=30s)
- `λ_FAILURE_PER_RUN_HOUR = 0.1946` (→ `p = 0.0018` at T=30s)

**Worked example at T=30s** (the source-of-truth block's reference point):

```
mean_cycle       = 1.11 × 30 = 33.3 s
UD(R)/R          = (λ_ms×mean_ms + λ_f×mean_f) / 3600
                 = (3.2432×70 + 0.1946×1920) / 3600 = 600.656/3600 = 0.166849
PPT              = 1,440 min − 90 min planned = 1,350 min = 81,000 s
R (Run Time)     = PPT / (1 + 0.166849) = 69,417.7 s
Availability     = R / PPT = 85.70%
```

**These results are independent of T** — Availability, unplanned minutes,
and event counts depend only on the λ rates and Planned Production Time,
never on cycle time:

- Micro-stops/machine-day = (R/3600)×λ_ms = **62.54**
- Failures/machine-day = (R/3600)×λ_f = **3.753**
- Unplanned `downtime_event`/machine-day = **66.29**
- Planned changeover/machine-day = **3** (fixed, one per shift)
- **Total `downtime_event`/machine-day = 69.29**
- Unplanned minutes/machine-day = **192.99**

Only cycle **count** (N) depends on T, as it should — a faster machine fits
more cycles into the same Run Time: N = R / mean_cycle(T). At T=30s,
N ≈ 2,085 cycles/machine-day.

`production_record` count is unaffected by any of this: 96 15-minute
buckets/line-day (see section 5's resolved production_record-grain note),
time-based, independent of T, rates, or N.

**Acceptance run (14 days × 8 machines = 112 machine-days; 14 days × 2
lines = 28 line-days):**

- `production_record`: 96 × 28 = **2,688** (line-days — section 5)
- `downtime_event`: 69.29 × 112 = **7,761** (machine-days — unaffected)
- Expected failure events: 3.753 × 112 ≈ **420**

### 4.1 Cycle time

Truncated normal: mean `1.11 × T`, sd `0.09 × T`, truncated to
`[0.95, 1.60] × T`, where `T = IDEAL_CYCLE_TIME_SECONDS` (per-machine,
simulator-config-only — see provenance note above). Sampled via rejection
on `random.gauss(mean, sd)`, redrawing until the value falls inside the
truncation bounds (no closed-form truncated-normal in stdlib).

### 4.2 Scrap

Bernoulli per unit, base rate **by shift**: 2.4% (A/morning), 2.8%
(B/afternoon), 3.8% (C/night). Simple average over three equal-length
shifts: `(2.4+2.8+3.8)/3 = 3.0%` exactly (corrected — an earlier draft of
this document said "≈3.1%", which doesn't reproduce from these three
numbers under any equal-weighting; not adopting an unequal-shift-length
weighting to force a different figure, since nothing anywhere establishes
unequal shift lengths). Target Quality is therefore **97.0%**, not 96.9%.
OEE target barely moves: `0.857 × 0.901 × 0.970 ≈ 74.9%`, still solidly
inside the 70-80% acceptance band.

### 4.3 Planned changeover

One per shift, duration uniform `[20, 40]` minutes (mean 30), logged with
`is_planned = true`. Three shifts/day → 90 min/day planned, which does
**not** count against Availability (it's already excluded from Planned
Production Time in section 4.0's derivation). Reason catalog dependency:
see section 4.6.

### 4.4 Micro-stop / failure boundary — 300 seconds, hard

A downtime event with `duration_seconds < 300` is classified
`reason = micro-stop`; `>= 300` is classified `reason = failure`. This is a
structural invariant (section 7), checkable directly against generated
data — no statistical sampling needed. Micro-stop duration draws are
clamped to `[20s, 299s]`, failure draws to `[300s, 14400s]`, so sampling
noise can never violate the boundary by construction.

### 4.5 Known ground truth — deliberate signals for downstream analytics

These exist so the Power BI dashboard and any later analysis (ANOVA,
correlation) has something *real* to find. Uniform rates across every
machine and shift would make a one-way ANOVA come back non-significant and
the Pareto come out flat — realistic-looking data that's analytically
useless.

- **Shift effect:** scrap by shift (section 4.2, 2.4%/2.8%/3.8%); micro-stop
  rate `×1.35` on shift C (night). A 3-level ANOVA with a real, detectable
  effect. Shift (A/B/C, business date) is read from the existing `Shift`
  model.
- **Post-failure warm-up:** for the first 15 cycles after a `failure` (not
  a `micro-stop`) ends, scrap `×2.5` and cycle time `×1.15`. The "failures
  don't only cost time" finding — a known, recoverable correlation between
  failure recovery and short-term Performance/Quality dips.
- **Bottleneck machine:** one machine per line — lowest `machine.id` on
  that line, for a stable, reproducible choice — gets failure rate `×1.8`
  and micro-stop rate `×1.4`. Makes the per-machine Pareto mean something,
  not just the per-reason one.

**Topology — decided (2026-08-16): 2 production lines × 4 machines each (8
total), bottleneck = 1 machine per line (lowest `machine.id` on that line) =
25% of the fleet.** This is the table's second row below. Section 6, 8, and
4.6 have been updated to use this topology's fleet-real rates rather than
section 4.0's flat baseline.

**Fleet-wide reconciliation with section 4.0.** `λ_MICRO_STOP_PER_RUN_HOUR`/`λ_FAILURE_PER_RUN_HOUR`
(section 4.0) are the **baseline** rate — not a fleet-average target lowered
elsewhere to compensate, since that would remove the very difference the
deliberate signals above are meant to create. But the shift-C micro-stop
bump is time-based (every machine spends 1/3 of its day in shift C, not
just special ones), so even a non-bottleneck machine's true time-averaged
rate sits slightly above section 4.0's flat figure (Availability ≈85.19%
vs. 85.70% — a modest, ~0.5pp gap). The bottleneck multiplier is larger and
machine-specific, and section 4.0's Availability/OEE figures do **not**
account for it at all. The true fleet-wide Availability/OEE that Section 8's
acceptance band actually gates is therefore lower than 85.70%/~75%, by an
amount that depends on what fraction of the 8 machines are bottleneck
machines — i.e. on the number of lines, which **has not been established
anywhere in this conversation**. Bounding it (holding scrap/shift effects
fixed, varying only the bottleneck fraction):

| Topology (bottleneck fraction) | Fleet Availability | Fleet OEE (×0.901×0.970) |
|---|---:|---:|
| 1 line / 8 machines (12.5%) | 84.26% | 73.6% |
| **2 lines / 4 machines (25%) — chosen** | **83.34%** | **72.8%** |
| 4 lines / 2 machines (50%) | 81.50% | 71.2% |

All three stay inside the 70-80% band. At the chosen 25% topology, margin
above the 70% floor is 2.8pp — comfortably wider than the 50% case's 1.2pp,
so the failure-rate band's own `±25%` noise pushing a real acceptance run
below 70% on an unlucky seed is not a practical concern here.

**Methodology note — a worked example of the error class Section 10 exists
to prevent.** An earlier draft of this table (84.17% / 83.20% / 81.31%)
computed fleet Availability by averaging the per-machine-type λ *rates*
first, then converting that single averaged rate to one Availability
figure. This is wrong: `Availability = 1/(1 + UD/R)` is a **convex**
function of the downtime ratio, so by Jensen's inequality,
`f(avg(rate)) ≤ avg(f(rate))` whenever machine types differ — averaging the
rate before converting systematically **understates** true fleet
Availability, and the gap grows with both the heterogeneity between machine
types and the bottleneck fraction (0.09pp off at 12.5% bottleneck, 0.19pp
off at 50%). The correct method: convert each machine type's own rate to
its own Availability first, *then* combine — here, a simple
machine-count-weighted average, since every machine shares the same Planned
Production Time (equivalent to pooling Run Time over Planned Production
Time across the fleet). This was caught by independent recomputation, not
by inspection — exactly the kind of silent, plausible-looking arithmetic
error a shared, single-sourced config module (section 10) can't prevent by
itself (the *inputs* were never duplicated or wrong), but that independent
verification of *derived* figures like this table still needs to catch
before they're treated as checkable constants.

### 4.6 Reason mix — an output, not an input

Target shares of total **unplanned** minutes: mechanical failure 34.1%,
material jam 20.9%, electrical failure 12.4%, material starvation 11.4%,
pneumatic failure 9.3%, sensor 6.2%, minor adjustment 5.7%. Top 3 = 67.4%,
top 4 = 78.8% — deliberately concentrated; 7 evenly-spread reasons would
make the cumulative Pareto curve nearly straight and communicate nothing.

**This can't be set directly** — the generator draws a Bernoulli-rate class
event plus a duration, not a targeted number of minutes. It decomposes
cleanly instead: the class split falls out of section 4.0's rates
(micro-stop 38.0% / failure 62.0% of unplanned minutes at the flat baseline
— matches the 34.1+12.4+9.3+6.2=62.0% failure / 20.9+11.4+5.7=38.0%
micro-stop split above), and each reason's share is that class's share times
a within-class categorical:

**Verified against the chosen topology (25% bottleneck), not assumed
negligible.** Fleet-real unplanned minutes/machine-day (section 6): 86.62
micro-stop min (74.25 events × 70s) + 138.58 failure min (4.33 events ×
1920s) = 225.20 total → micro-stop 38.46% / failure 61.54%, a shift of only
+0.46pp toward micro-stops versus the flat 38.0%/62.0% baseline. Every
individual reason's `±20%`-relative acceptance band (section 8) is at least
±1.14 percentage points (the smallest target share, minor adjustment at
5.7%, allows ±1.14pp) — a uniform 0.46pp class-level shift, applied
proportionally within each class, stays well inside every reason's band.
**No correction needed to the percentages below.**

- **Failure class:** mechanical 55%, electrical 20%, pneumatic 15%, sensor
  10%.
- **Micro-stop class:** material jam 55%, starvation 30%, minor adjustment
  15%.

**Mechanism:** draw the class first (from the same rate that drives section
4.0 — micro-stop vs. failure), then draw the reason *within* that class
from the categorical above. Duration comes from the same class-level
distribution for every reason in that class — this is why share-of-minutes
equals share-of-events within a class. **This corrects ADR 0004's original
wording**, which said durations come "from separate distributions per
`downtime_reason`"; the actual, implementable design is one distribution
**per class** (micro-stop, failure), not per individual reason — solving
backwards from 7 target shares to 7 independent per-reason rates would be
solvable but adds no analytical benefit over the class-level model.

**Catalog dependency — Step 1, resolved.** Only two `downtime_reason` rows
existed before Step 1 (`MTN-P` planned, `FLA-M` unplanned —
`scripts/seed_demo.py`). Verifying against the actual file corrected an
earlier assumption here: `FLA-M` ("Falla mecanica") maps onto exactly one of
the 7 target reasons (`mechanical`, Failure class); `MTN-P` ("Mantenimiento
planeado") does **not** map onto any of the 7 — the mix above is scoped to
*unplanned* minutes only, and `MTN-P` is planned by construction. So the gap
was **6** new rows, not 5. A 7th new row was added on top of that: a
dedicated `CHG-P` ("Cambio de formato") for section 4.3's planned changeover,
kept separate from `MTN-P` on purpose — mixing maintenance and changeover
under one code would block any future analysis that needs to tell them
apart. Final catalog (9 rows, `scripts/seed_demo.py`):

| Code | Name | `default_is_planned` | Maps to |
|---|---|---|---|
| `MTN-P` | Mantenimiento planeado | true | (unused by the reason mix) |
| `CHG-P` | Cambio de formato | true | section 4.3 planned changeover |
| `FLA-M` | Falla mecanica | false | Failure class: mechanical |
| `FLA-E` | Falla electrica | false | Failure class: electrical |
| `FLA-N` | Falla neumatica | false | Failure class: pneumatic |
| `FLA-S` | Falla de sensor | false | Failure class: sensor |
| `ATC-M` | Atasco de material | false | Micro-stop class: material_jam |
| `DES-M` | Desabasto de material | false | Micro-stop class: starvation |
| `AJT-M` | Ajuste menor | false | Micro-stop class: minor_adjustment |

**Known duplication (Step 3): reason codes are redefined, not imported,
across two files — deliberately, with a documented failure mode.**
`scripts/seed_demo.py` (which seeds the actual `downtime_reason` rows) and
`scripts/simulator/config.py` (which drives the generator's own reason-mix
logic) each define their own copy of the eight code strings the generator
needs (`CHG-P`, `FLA-M`, `FLA-E`, `FLA-N`, `FLA-S`, `ATC-M`, `DES-M`,
`AJT-M`). Seven of the eight share both the same constant *name* and the
same string *value* across both files; the eighth (`"FLA-M"`) shares only
the value — `scripts/seed_demo.py` names its constant
`REASON_UNPLANNED_CODE` (predating the reason-mix catalog work),
`scripts/simulator/config.py` names it `REASON_FAILURE_MECHANICAL_CODE`.
`scripts/simulator/config.py`'s own docstring for these constants explains
*why* they're redefined rather than imported (`scripts/seed_demo.py` is a
one-off dev seed, not a canonical source), but the risk is real either
way: if either file's string value is retyped and the other isn't updated
to match, the two files silently disagree about what a code means, and
nothing catches that by inspection.

What actually catches it: `generate()`'s `_validate()`
(`scripts/simulator/generator.py`) checks every code the generator needs
against the caller-supplied `SimulatorConfig.reason_ids` mapping
(`downtime_reason.code -> DB id`) and raises `ValueError` immediately if
any are missing — covered by
`tests/unit/test_simulator_generator.py::test_missing_reason_code_raises_before_generation`.
Since `reason_ids` has to be built by querying the real `downtime_reason`
table (by whichever future step wires the generator to a live DB — Step
3+ transport, not built yet), a drift between `scripts/seed_demo.py`'s
seeded codes and `scripts/simulator/config.py`'s expected codes surfaces
as a hard failure the first time that mapping is built and passed in —
not as silently-wrong data. This is fail-fast-on-use, not compile-time or
automatic sync: nothing prevents the two files' constants from drifting
apart *before* that point, and no linter or test in this repository
currently cross-checks `scripts/seed_demo.py`'s catalog against
`scripts/simulator/config.py`'s expected codes directly. If this class of
bug ever actually happens, the fix is a shared constants module both files
import from — not attempted now, since it would mean promoting one of two
dev/build scripts to canonical-source status (or introducing a third
module) for a duplication whose failure mode is already caught, just later
than compile time, by `_validate()`.

### 4.7 Simplification, named as a future upgrade

A constant `λ` per run-hour is still a **memoryless-hazard** model — the
probability of a stoppage in the next unit of run time doesn't depend on
how long the machine has run since its last one. Real equipment wear-out
hazard is usually *not* memoryless (hazard increases with running time). A
Weibull hazard with shape `k ≈ 1.5` (increasing hazard, expressed over
cumulative run time rather than cycle count) is the documented future
upgrade path — deferred because the constant-rate model already reaches the
acceptance OEE band and is far simpler to reason about and debug during the
MAS build. Not adopted now to avoid solving a realism problem that hasn't
been shown to matter yet.

## 5. Persistence granularity

- **Simulation:** per-cycle (every individual unit cycle is simulated:
  drawn cycle time, scrap outcome, and any triggered stoppage).
- **Persistence:** cycles are aggregated into one `production_record` per
  15-minute bucket **per line** (`total_count`, `good_count`,
  `ideal_cycle_time_seconds` for that bucket, summed across every machine
  on the line) — matching the existing `production_record` schema's grain
  and the 96-buckets/line/day figure the write-volume arithmetic
  (section 6) already depends on. Each stoppage (micro-stop, failure, or
  planned changeover) is persisted as exactly **one row** in
  `downtime_event`, at its own actual `started_at`/`ended_at`, per
  machine — never aggregated, since `downtime_event` is already
  event-grained (and machine-grained, via its nullable `machine_id`) in
  the schema.

**Corrected (Step 3): `production_record` grain is per line, not per
machine — the text above originally said "per machine," and was wrong.**
`production_record` (`src/paro/db/models.py:145-165`) has no `machine_id`
column — the model's own docstring says "a production count over a time
interval for a **line**." This spec originally assumed a per-machine
grain throughout (the "96-buckets/machine/day" figure this section used
to state, and every number derived from it in sections 4.0 and 6 below),
which doesn't exist in the schema and never did. Caught during Step 3
implementation (`scripts/simulator/generator.py`'s `_bucket_line`), not
before — verified twice (independent grep, then a direct read of the
model file) before committing to the per-line design, and only surfaced
to review as a line item in the fix that follows, not folded into the
commit that introduced it. Consequence: `ideal_cycle_time_seconds` is a
**per-line** value (`LineConfig.ideal_cycle_time_seconds`, shared by every
machine on that line), not per-machine as section 4.1 originally implied;
every machine on a line still draws its own cycle times independently
(own RNG substream, same target `T`), but the bucketed `production_record`
row sums `total_count`/`good_count` across all of a line's machines for
that 15-minute window. Every `production_record` count in sections 4.0
and 6 below, and the SMOKE structural check in section 7, are corrected
to the per-line figure (14 days × 2 lines = 28 line-days at acceptance
scale, not 14 days × 8 machines = 112 machine-days); `downtime_event`
counts are untouched by this correction since that table was already
per-machine-grained (`machine_id` FK) before Step 3 and stays so.

**Empty buckets are written explicitly, not skipped.** A stoppage spanning
part or all of a 15-minute window still gets a `production_record` row for
that window — `total_count=0, good_count=0` if nothing was produced. This is
schema-legal: `valid_counts` (`src/paro/db/models.py:151`) is
`CheckConstraint("good_count >= 0 AND good_count <= total_count", ...)`, and
`ProductionRecordCreate.total_count: int = Field(ge=0)`
(`src/paro/api/schemas/production.py:38`) — both allow zero. Writing zeros
instead of skipping keeps "exactly 96 contiguous, non-overlapping buckets
per line per simulated day, no gaps" a deterministic structural
invariant (section 7): skipping would make row count stoppage-pattern-
dependent, and "correctly skipped" indistinguishable from "bug dropped a
bucket" — exactly the distinction the QA Agent exists to catch. That
invariant only exists *because* this choice was made; don't "optimize" the
empty buckets away later without also dropping the check that depends on
them.

**Do not change the 15-minute bucket granularity to reduce write volume.**
Hourly buckets would cut `production_record` from 2,688 to 672 and look
like an easy win against the rate-limit arithmetic below — but persistence
granularity is a decision about what the dashboard needs (an hourly OEE
trend is coarser than what `docs/analytics.md`'s per-record grain supports
today), not something to trade away to work around a transport constraint
that already has its own fix (section 6). If write volume is ever a problem
again, the fix belongs in section 6, not here.

## 6. Rate-limit strategy

### The problem, with numbers

`src/paro/api/rate_limit.py` configures `Limiter(key_func=get_remote_address)`
— one shared budget per IP, at `30/minute` on `POST /downtime-events`,
`PATCH /downtime-events/{id}`, and `POST /production-records`
(`src/paro/api/routers/downtime.py:35,76`, `src/paro/api/routers/production.py:20`).
A single-process simulator writes from one IP, so all three endpoints share
one 30-requests/minute budget for the whole run.

| Phase | production_record | downtime_event | Total writes | Time @ 30/min |
|---|---:|---:|---:|---:|
| Smoke (1 day × 2 machines, same line) | 96 | 139 | 235 | 7.8 min |
| Smoke + idempotency re-run | 192 | 278 | 470 | 15.7 min |
| 5 rounds (smoke + idempotency each) | 960 | 1,390 | 2,350 | 78.3 min (1h18m) |
| Acceptance run (14d × 8m, once) | 2,688 | 9,137 | 11,825 | 394.2 min (6h34m) |
| **Full Developer/QA loop (5 rounds + acceptance)** | **3,648** | **10,527** | **14,175** | **~472.5 min (~7h53m)** |

(Smoke/idempotency/5-rounds rows use section 4.0's flat baseline rate —
which specific 2 machines a smoke run picks, and therefore whether either is
the bottleneck machine, isn't fixed by this spec, so the flat rate is kept
as an order-of-magnitude estimate; it doesn't affect those rounds'
structural-only pass/fail. The `production_record` column for these three
rows carries a second, new assumption the pre-Step-3 per-machine model
never had to make: that the smoke run's 2 machines share one line (96
buckets/day, matching `scripts/simulator/generator.py`'s own smoke-scale
test setup) rather than sitting on two different lines (192 buckets/day).
Also order-of-magnitude, for the same reason — it doesn't affect
structural-only pass/fail. The acceptance run and full-loop rows use the
chosen topology's fleet-real rate — 25% of the fleet is the bottleneck
machine, section 4.5 — since that run deterministically covers all 8
machines: 74.25 micro-stop + 4.33 failure = 78.58 unplanned events/
machine-day, + 3 planned = 81.58 total `downtime_event`/machine-day, vs.
69.29 at the flat baseline (+17.7%). `downtime_event` = 81.58 × 112 =
9,136.85 → 9,137, unaffected by the production_record-grain correction.
`production_record` at acceptance scale is exact, not order-of-magnitude:
96 × 28 line-days = 2,688 (section 5).)

This isn't just the acceptance run — the limiter blocks the *entire*
round-trip loop the QA Agent's cap depends on being fast (see
[ADR 0004](adr/0004-simulator-multi-agent-architecture.md)). Client-side
pacing (wait out the limiter) was considered and is not viable: it turns a
5-round loop meant to run in seconds into a half-day-plus wait.

### Options considered

- **Per-source higher limit via env var — REJECTED, not implementable.**
  `key_func=get_remote_address` resolves the rate-limit key from the
  connection's IP address *before* the request body is read or parsed —
  `source` lives in the JSON body. The limiter has already decided which
  bucket to charge before it could possibly know who's writing. Resolving
  the key post-parse would mean re-architecting how `slowapi` hooks into
  the request lifecycle in this app — fighting the library's design rather
  than working with it. Not pursued.
- **Blanket bypass in test environment — REJECTED.** Works mechanically,
  but keys the exemption off "we're in the test environment" rather than an
  explicit credential, and leaves no record of who or what was authorized
  to skip the limit. Same practical effect as the chosen option, worse
  security posture — an env-detection bypass exempts *anything* running in
  that environment, not just the simulator.
- **Bulk/batch ingest endpoint — DEFERRED, not rejected.** A `POST
  /downtime-events/batch`-style endpoint accepting N rows in one request is
  the correct long-term answer for real ingestion — it solves the write-
  volume problem and the rate-limit problem together, for the simulator and
  for any real integration writing in bulk. Not built now: it's new API
  surface needing its own schema, partial-validation semantics (what
  happens when row 47 of 100 fails?), and per-row error reporting — a
  separate, later task. Named here as the future direction so it isn't
  reinvented under a different name later.

### Decision: trusted-ingest exemption, env-gated

Implement in a **later task** (specced here, not built now):

- `PARO_TRUSTED_INGEST_TOKEN` — new env var. **Unset by default**, meaning
  no exemption is possible at all unless an operator deliberately
  configures one. Production behavior is unchanged unless someone opts in.
- `exempt_when` on the existing `@limiter.limit(...)` decorators (confirmed
  supported by the installed `slowapi==0.1.10` —
  `.venv/Lib/site-packages/slowapi/extension.py:788-826`; the predicate can
  read the `Request`, per the docstring at line 812-813). The predicate
  returns `True` only when `PARO_TRUSTED_INGEST_TOKEN` is configured **and**
  the incoming request carries a matching header (e.g.
  `X-Paro-Trusted-Ingest`).
- The simulator's API client sends that header on every write, using the
  same env var value.

**Why this is not "skipping the limiter is skipping the real path"** (a
characterization from an earlier framing of this decision that was wrong):
an exemption from the rate limiter still exercises every other piece of the
API the ADR wanted the simulator to go through — Pydantic validation
(tz-awareness, `ended_at > started_at`, `good_count <= total_count`),
serialization, the repository layer's `source`+`external_id` idempotency,
and every DB `CHECK`/`UNIQUE`/`FK` constraint. The rate limiter is the one
piece of that path whose entire purpose is defending against anonymous
abuse from the public internet — a purpose the simulator, running as a
known, credentialed, trusted client, doesn't need exercised on every one of
21,823 writes.

**Follow-up, not part of this build:** the rate limiter itself still
deserves a test — it has none today. A small, dedicated test (fire 35
requests without the trusted-ingest header, assert the 31st gets `429`) is
the right shape for that, not an incidental 10-hour side effect of running
the simulator. Track as a separate task.

### 429 handling

The simulator's API client retries a `429` with exponential backoff (this
applies regardless of the trusted-ingest exemption — a future bulk endpoint,
a misconfigured token, or a second concurrent simulator run could all still
produce one). **A `429` that was correctly backed off and retried is not a
QA failure.** Only an unretried `429`, or one that exhausts its retry budget
without eventually succeeding, counts as a failure (see section 7).

## 7. Two-tier QA checks

Two tiers, run at different scales for a specific reason: **structural
checks are worth more per round than statistical ones.** They're
deterministic (no sample-size false positives — a broken invariant is
broken on 4 rows or 40,000), and they catch the bugs a simulator actually
has (an off-by-one on bucket alignment, a boundary comparison using `<=`
instead of `<`, two overlapping stoppages on one machine). Running
statistical rate checks against a tiny smoke sample produces noise, not
signal — a 2-machine, 1-day sample can easily show zero failures or double
the target rate by chance alone, burning a round of the QA Agent's cap over
nothing. Statistical banding is deferred to the one full-scale run where the
sample is actually large enough to mean something (section 8).

### SMOKE — every round (1 day × 2 machines)

- No exceptions during generation or transport.
- Every written row satisfies its schema's `CHECK`/`UNIQUE`/`FK` constraints
  (the same set `tests/integration` verifies).
- Structural invariants, checked against the **generated event stream**
  before transport (cheaper, and catches the bug at its source):
  - No two `downtime_event` rows for the same machine have overlapping
    `[started_at, ended_at)` intervals.
  - Every `downtime_event` references a valid `downtime_reason` FK, and its
    `is_planned` flag agrees with that catalog row's `default_is_planned`.
  - Every `production_record`: `good_count <= total_count`.
  - Every `downtime_event`'s `reason` matches the 300-second
    micro-stop/failure boundary (section 4.4) exactly — `duration_seconds <
    300` implies `micro-stop`, `>= 300` implies `failure` (planned
    changeovers excluded from this check; they're `is_planned=true` by
    construction).
  - Every `production_record`'s `[interval_start, interval_end)` aligns to
    a 15-minute boundary, and no single simulated cycle is split across two
    buckets and double-counted in both.
  - **Exactly 96 contiguous, non-overlapping `production_record` buckets per
    line per simulated day, covering the full 24 hours with no gaps** —
    only checkable because empty buckets are written explicitly rather than
    skipped (section 5). A dropped bucket and a deliberately-skipped one are
    otherwise indistinguishable; this is the check that tells them apart.
  - No naive (tz-unaware) timestamp anywhere in the generated stream.

### IDEMPOTENCY — every round

Re-run SMOKE with the identical seed and config. Must add **zero** new
rows — every write resolves as an idempotent no-op via the existing
`source`+`external_id` repository behavior (`src/paro/db/repositories.py`).
Counted in the rate-limit arithmetic (section 6) as doubling the smoke
round's write volume, since every request still counts against the limiter
even when it resolves as a no-op.

### ACCEPTANCE — once, at the end (14 days × 8 machines)

- All SMOKE structural checks, at full scale.
- Statistical bands (section 8): failure/micro-stop/scrap rates within
  their configured target ranges, OEE within 70-80%, reason mix
  distribution matches the configured proportions within tolerance.

## 8. Acceptance bands and sample-size justification

For a rare-event count with expectation *n*, the relative standard error is
`sqrt(n)/n`. At the acceptance scale (14 days × 8 machines — the stated
minimum for this gate), the expected failure count at the chosen topology's
fleet-real rate (section 6) is **≈485**, not the flat-baseline ≈420 from
section 4.0: `sqrt(485)/485 ≈ 4.54%` relative error. A `±25%` band is
therefore **≈5.5σ** of headroom — *more* comfortable than the flat-baseline
figure, not less, since a higher expected count only shrinks the relative
sampling noise. This is exactly the "makes the band more comfortable, not
broken" case: no tightening or widening is warranted, and none is applied.
At the smoke scale (2 machines, 1 day), the
same rare events number in the single digits, where relative error is large
enough that a clean run and a subtly-broken one look statistically
indistinguishable — which is exactly why statistical banding is deferred to
this one full-scale run instead of checked every round (section 7).

Bands, all re-justified against the section 4.0 converged figures:

- **Scrap rate:** `±0.5` percentage points, absolute.
- **Micro-stop rate:** `±15%`, relative.
- **Failure rate:** `±25%`, relative — the widest band, because it's the
  rarest event (~420 expected occurrences); this width is unavoidable given
  the sample size and is not to be tightened.
- **Mean cycle time:** `±3%`, relative.
- **OEE:** `70%–80%`, computed the same way `GET /api/v1/oee` computes it —
  **never reimplemented as a SQL ratio for this check** (same rule
  `docs/analytics.md`'s "Non-negotiable design rule" states for the
  analytics views, applying identically here). This is the
  integrating check: it catches combinations of small per-parameter drifts
  that no individual band would flag on its own.
- **Reason mix:** each of the 7 reasons' observed share within `±20%`,
  relative, of its target share (section 4.6).

Minimum acceptance run: **14 days × 8 machines**, unchanged.

## 9. Retry semantics for the QA Agent

Restating section 6: a `429` response that the simulator's client correctly
backed off and retried, eventually succeeding, is **not** a QA failure — it
means the trusted-ingest exemption wasn't configured for that run, or the
limiter fired for an unrelated reason, and the client handled it exactly as
designed. Only two things count as a QA failure here: an unretried `429`
(the client gave up immediately), or a retry sequence that exhausted its
budget without the write ever succeeding.

## 10. Config module contract

Every numeric parameter in section 4 lives in exactly one module (e.g.
`scripts/simulator/config.py`), as a named constant with units in the name.
Both the Developer Agent's simulator code and the QA Agent's check code
import from this one module — no magic numbers duplicated between the code
that generates data and the code that checks it. If the QA Agent's boundary
check and the Developer Agent's classification logic ever used two
independently-typed `300`s, a future edit to one and not the other would
silently break the invariant without either agent's tests catching it.

The confirmed constant set (names indicative, final naming is Step 4's
call, but no value here may drift from section 4 without a spec revision):

```
MASTER_SEED = 42                    # fixed, confirmed 2026-08-16
IDEAL_CYCLE_TIME_SECONDS            # per machine, simulator-config only — 4.1
CYCLE_TIME_MEAN_MULTIPLIER = 1.11
CYCLE_TIME_SD_MULTIPLIER = 0.09
CYCLE_TIME_TRUNC_MIN_MULTIPLIER = 0.95
CYCLE_TIME_TRUNC_MAX_MULTIPLIER = 1.60

MICRO_STOP_LAMBDA_PER_RUN_HOUR = 3.2432
MICRO_STOP_DURATION_MU = 4.0943      # ln(60)
MICRO_STOP_DURATION_SIGMA = 0.5552
MICRO_STOP_DURATION_MIN_SECONDS = 20
MICRO_STOP_DURATION_MAX_SECONDS = 299

FAILURE_LAMBDA_PER_RUN_HOUR = 0.1946
FAILURE_DURATION_MU = 7.3132         # ln(1500)
FAILURE_DURATION_SIGMA = 0.7028
FAILURE_DURATION_MIN_SECONDS = 300
FAILURE_DURATION_MAX_SECONDS = 14400

MICRO_STOP_FAILURE_BOUNDARY_SECONDS = 300

PLANNED_CHANGEOVERS_PER_SHIFT = 1
PLANNED_CHANGEOVER_DURATION_MIN_MINUTES = 20
PLANNED_CHANGEOVER_DURATION_MAX_MINUTES = 40

SCRAP_PROBABILITY_BY_SHIFT = {"A": 0.024, "B": 0.028, "C": 0.038}

SHIFT_C_MICRO_STOP_RATE_MULTIPLIER = 1.35
WARMUP_CYCLE_COUNT = 15
WARMUP_SCRAP_MULTIPLIER = 2.5
WARMUP_CYCLE_TIME_MULTIPLIER = 1.15
BOTTLENECK_FAILURE_RATE_MULTIPLIER = 1.8
BOTTLENECK_MICRO_STOP_RATE_MULTIPLIER = 1.4

REASON_MIX_FAILURE_CLASS = {"mechanical": 0.55, "electrical": 0.20, "pneumatic": 0.15, "sensor": 0.10}
REASON_MIX_MICRO_STOP_CLASS = {"material_jam": 0.55, "starvation": 0.30, "minor_adjustment": 0.15}

PRODUCTION_BUCKET_MINUTES = 15
ACCEPTANCE_DURATION_DAYS = 14
ACCEPTANCE_MACHINE_COUNT = 8
SMOKE_DURATION_DAYS = 1
SMOKE_MACHINE_COUNT = 2

ACCEPTANCE_BAND_SCRAP_PP = 0.005                 # absolute
ACCEPTANCE_BAND_MICRO_STOP_RELATIVE = 0.15
ACCEPTANCE_BAND_FAILURE_RELATIVE = 0.25
ACCEPTANCE_BAND_CYCLE_TIME_RELATIVE = 0.03
ACCEPTANCE_BAND_OEE_MIN = 0.70
ACCEPTANCE_BAND_OEE_MAX = 0.80
ACCEPTANCE_BAND_REASON_MIX_RELATIVE = 0.20
```

**float vs. Decimal — resolved (Step 3), and binding on every future
module that samples from these constants.** Every constant above is
`float`, not `Decimal`, and every RNG draw that consumes them
(`random.gauss`, `random.lognormvariate`, `random.uniform`,
`random.random()`, `random.choices`) stays in `float` end to end. This is
not an exception to the project's "every numeric calculation uses
Decimal, never float" rule — it's outside that rule's scope. The stdlib's
`random` module has no Decimal-typed distribution sampler (no
`Decimal`-native Gaussian, lognormal, or weighted-categorical draw exists
anywhere in the standard library), so implementing distribution sampling
in Decimal would mean hand-rolling a Box-Muller-equivalent purely to
avoid float, for a synthetic-data generator where the whole point of the
draw is randomized realism, not reproducible financial precision. The
rule's actual target is any quantity that gets *persisted or compared for
correctness* — and every such quantity in this module stays outside the
float path entirely: `ideal_cycle_time_seconds` is supplied by the caller
as `Decimal` (`LineConfig.ideal_cycle_time_seconds`,
`scripts/simulator/model.py`) and passed through to every
`ProductionRecordDraft` unchanged — never computed from, or rounded
through, any of the float constants above. `total_count`/`good_count` are
plain `int`, incremented once per cycle, never derived from a float
division or ratio. The only float-derived values in the generator's
output are `datetime` timestamps (`started_at`/`ended_at`/
`interval_start`/`interval_end`), which were never a Decimal concern to
begin with — `datetime`/`timedelta` accept float seconds natively, same
as any other duration arithmetic in this codebase.

Precedent for the rest of the project, not just this module: statistical/
RNG sampling code is float by construction and exempt from the Decimal
rule; anything that gets written to a schema column typed
`Numeric`/`Decimal`, or compared against an acceptance band, is not, and
must stay `Decimal` (or `int`, where the schema says so) all the way
through, with no float step in between. This module is the citable
example of both halves of that line, not just the first one.

## Out of scope for this document

- The actual simulator source code, and the actual QA Agent check code —
  Steps 1-5, not started.
- The 7 `downtime_reason` catalog rows (section 4.6) were Step 1 — done in
  `scripts/seed_demo.py`, not in this document.
- The trusted-ingest exemption's implementation in
  `src/paro/api/rate_limit.py` and the routers — specced in section 6, not
  built here (Step 2).
- The dedicated rate-limiter test (section 6's follow-up) — separate task.
- The bulk/batch ingest endpoint (section 6) — deferred, named only.
- The Weibull hazard upgrade (section 4.7) — future, named only.
- LangGraph/Ollama orchestration (Step 5) — build-tool dependencies only,
  must never enter the PARO API's runtime dependency list.
