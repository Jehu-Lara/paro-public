# Render deployment contract

PARO's public demo uses one web service and one 15-minute cron. The web service
remains read-only to anonymous users; the cron is the only holder of both write
credentials.

## Web service

- Start: `uvicorn paro.main:app --host 0.0.0.0 --port $PORT`
- Health check: `/health`
- Public: `/health`, `/ready`, `/docs`, `/api/v1/oee`,
  `/api/v1/demo/overview`, `/demo`
- Secrets: `PARO_DATABASE_URL`, `PARO_API_KEY`,
  `PARO_TRUSTED_INGEST_TOKEN`

The web service must hold the trusted-ingest token because it verifies the
cron's `X-Paro-Trusted-Ingest` header before granting the rate-limit
exemption. The API key and trusted-ingest token are independent values; each
value must match its counterpart on the cron.

## Cron

- Schedule: `*/15 * * * *`
- Start: `python -m scripts.run_live_demo`
- The first run idempotently creates only the simulator's missing downtime-reason
  catalog rows; it does not execute the historical development seed.
- Required: `PARO_DATABASE_URL`, `PARO_BASE_URL`, `PARO_API_KEY`,
  `PARO_TRUSTED_INGEST_TOKEN`
- `PARO_API_KEY` authenticates writes. `PARO_TRUSTED_INGEST_TOKEN` only
  exempts the trusted cron from the 30/minute limit; it never authenticates.

Never place secret values in this file, Render build logs, Power BI, browser
assets, screenshots, or Git history.

## Activation order

1. Configure `PARO_API_KEY` and `PARO_TRUSTED_INGEST_TOKEN` on the existing
   web service and redeploy.
2. Verify anonymous writes return 401 and public reads remain available.
3. Deploy the code containing the dual-header cron client.
4. Configure both cron secrets and `PARO_BASE_URL`.
5. Run once manually, then enable the schedule.
6. Observe two consecutive runs and reconcile API, database, dashboard, and
   logs before calling the feed ready.

## Historical simulator compatibility

The original `simulator` source retains its legacy relative external IDs so a
rerun conflicts with or reuses the historical `(source, external_id)` keys
instead of silently inserting a second copy. Absolute IDs are opt-in through
an explicit namespace and are mandatory for the rolling source
`simulator-live-v1`. Do not mix historical and live sources in one analytical
query.
