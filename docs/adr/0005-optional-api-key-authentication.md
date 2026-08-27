# ADR 0005 - Optional API-key authentication for write endpoints

- **Status:** accepted — implemented
- **Date:** 2026-08-19

## Context

`README.md`'s "Out of MVP scope" table has always listed authentication
as "out of scope by design," and the live demo's own callout says "no
authentication... don't send anything sensitive to it." Both statements
are honest about the current deployment, but neither one distinguishes
"we decided not to build this" from "we never considered it." A reviewer
looking at an exposed `POST /api/v1/downtime-events` with no auth has no
way to tell which is true from the repo alone.

The rate limiter already solved a structurally identical problem in
`docs/simulator-spec.md` section 6: `PARO_TRUSTED_INGEST_TOKEN`, unset by
default, exempts a trusted caller from the 30/minute limit only when both
configured and presented via a header, compared with
`secrets.compare_digest`. That mechanism doesn't touch the actual
question here — a rate-limit exemption isn't authentication — but its
shape (env var, unset = no effect, constant-time header comparison) is
exactly the right shape for a real answer.

## Decision

Add `PARO_API_KEY` (`src/paro/config.py`, unset by default, same as
`trusted_ingest_token`) and a `require_api_key` FastAPI dependency
(`src/paro/api/auth.py`) wired into the three write endpoints only —
`POST /downtime-events`, `PATCH /downtime-events/{id}`,
`POST /production-records`. In local and other non-production environments,
an unset key remains a no-op. In `PARO_ENV=production`, a missing or blank
key fails application startup, makes `/ready` return `503` if invoked
without lifespan, and makes the write dependency fail closed. When set, a
request missing the `X-API-Key` header or sending one that doesn't match
(constant-time compared) gets `401`.

`GET /health` and `GET /oee` are never gated — they're read-only, and
gating them would break the "browse the live docs/data" part of the
demo for anyone not sending a key, which isn't the risk this ADR closes.

No new dependency: this reuses the same `Settings`/`Depends` machinery
already in the codebase, not a new auth library — there's no session
model, no user accounts, no JWT. It answers "is there authentication,"
not "is there a full authorization system," which was never the
question.

## Consequences

- A production process cannot become ready or accept writes unless the
  operator sets `PARO_API_KEY`. Local development remains key-optional.
- `README.md`'s "Out of MVP scope" table and "Limitations" section are
  updated to describe the actual, current mechanism instead of a blanket
  "out of scope" — see the README diff in the same change.
- Production requires one environment variable before startup; no code
  change or alternate authentication mode is needed.
- Still out of scope, deliberately: multiple keys/rotation, per-client
  keys, JWT/OAuth, RBAC. If a future need for those arises, that's its
  own ADR, not an extension bolted onto this one.
