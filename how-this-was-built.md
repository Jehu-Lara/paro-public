# How this was built

This project was built with AI-assisted implementation (Claude Code)
under a review discipline the human owner set and enforced throughout —
not "write some code and skim it," but a specific, repeatable process.
This page documents what that process actually was, using real examples
from this repo's own history rather than general claims about AI use.

## What the human decided

Every architecture and domain decision in this repo was made by the
project owner, not generated and accepted wholesale: the OEE formula and
its edge-case rules (zero-denominator handling, `Performance` capping,
open-event treatment — see `docs/oee-definition.md`), the schema and its
idempotency strategy (`source` + `external_id`), the interval-overlap
arithmetic that keeps downtime minutes from double-counting, and —
concentrated in the industrial simulator (`docs/simulator-spec.md`,
`docs/adr/0004-simulator-multi-agent-architecture.md`) — every
statistical parameter (failure/micro-stop rates, shift effects, the
25%-bottleneck topology), every retry-semantics choice (a `5xx` fails
immediately rather than retrying, because in this codebase it means an
unhandled-exception bug, not transient noise), and every scope boundary
(what got built now vs. deferred, and why).

## Where AI agents were used, and how the plan changed under real review

`docs/adr/0004-simulator-multi-agent-architecture.md` originally proposed
building the simulator itself via a two-agent loop: a Developer Agent
writing code, gated by a QA Agent, iterating without a human in the
round — because at the time, no human was going to hand-write a
multi-file event simulator. That's a real, load-bearing example of
"where an AI agent was used" that's worth being specific about, because
the plan didn't survive contact with the actual work:

By the time the simulator's QA-checking step was reached, the simulator
itself (`scripts/simulator/generator.py`, `client.py`, `transport.py`,
`scripts/simulate_production.py`) had already been written and reviewed
by hand, commit by commit, through the process described below — there
was no more code-generation task left for a Developer Agent to gate. The
ADR was amended in place to say so
(`## Revision (2026-08-18)`, commit `ad51e81`), rather than left
describing an architecture that was quietly never finished. The
original "Tech stack for orchestration" section (LangGraph vs. CrewAI
vs. AutoGen) is still in the document, unedited, as a record of the
evaluation that was actually done — not deleted to make the ADR look
like it always matched what got built.

## How AI-generated work was reviewed

Three concrete mechanisms, not a general "I reviewed it" claim:

**Corrections get surfaced before they get buried in a commit.** Step 3
of the simulator build implemented `production_record` as one row per
*line* per 15-minute window (the table has no `machine_id` column — the
generator's own per-cycle simulation is per-machine, but persistence
isn't). That correction changed a spec figure from 10,752 rows to 2,688
at acceptance scale. The first version of that fix announced the number
change only in its own commit message, after the fact — caught on
review and treated as its own problem, not folded silently into the next
commit: a dedicated follow-up commit
(`283770c`, `docs: correct production_record per-line figures in
simulator-spec.md`) fixed every stale figure the change had introduced
across four sections of the spec, explicitly citing the original commit
it corrected.

**Derived numbers get independently reproduced before they're trusted.**
The QA check suite (`scripts/simulator/qa.py`) computes each statistical
acceptance band's expected center generically, from the same rate
constants the generator itself uses — deliberately not copied from the
spec's own hand-worked example numbers, so the two can't silently drift
apart. Before that generic formula was trusted against real generated
data, two dedicated tests
(`tests/unit/test_simulator_qa.py::test_flat_baseline_reproduces_section_4_0`
and `::test_chosen_topology_reproduces_section_4_5`) confirmed it
reproduces the spec's own separately hand-derived figures (62.54
micro-stops / 3.753 failures per machine-day at the flat baseline; 74.25
/ 4.33 at the chosen topology) to within a fraction of a percent, before
being relied on to check anything else.

**Nothing gets committed from a description of a diff — only from the
diff itself.** Every step in this build required the actual file content
or command output pasted into the review, not a summary of it ("added
error handling," "updated the tests") — verbatim, checked line by line,
with an explicit pass/fail verdict before a commit happened. Multiple
times across this build, a step that was reported as done had to be
redone because what was shown wasn't actually the file contents.

## What this doc is not

Not a claim that every line was manually typed, and not a claim that
review makes mistakes impossible — the corrections above are evidence a
mistake happened and was caught, not evidence mistakes don't happen. It's
a record of the specific mechanisms this repo actually used to catch
them, so that claim is checkable against real commits instead of taken
on faith.
