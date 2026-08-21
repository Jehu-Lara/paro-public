# Render deployment contract

PARO's public demo uses one web service and one 15-minute cron. The web service
remains read-only to anonymous users; the cron is the only holder of both write
credentials.

## Web service

- Start: `uvicorn paro.main:app --host 0.0.0.0 --port $PORT`
- Health check: `/health`
- Public: `/health`, `/ready`, `/docs`, `/api/v1/oee`,
  `/api/v1/demo/overview`, `/demo`
- Secrets: `PARO_DATABASE_URL`, `PARO_API_KEY`

## Cron

- Schedule: `*/15 * * * *`
- Start: `python -m scripts.run_live_demo`
- Required: `PARO_DATABASE_URL`, `PARO_BASE_URL`, `PARO_API_KEY`,
  `PARO_TRUSTED_INGEST_TOKEN`
- `PARO_API_KEY` authenticates writes. `PARO_TRUSTED_INGEST_TOKEN` only
  exempts the trusted cron from the 30/minute limit; it never authenticates.

Never place secret values in this file, Render build logs, Power BI, browser
assets, screenshots, or Git history.

## Activation order

1. Configure `PARO_API_KEY` on the existing web service and redeploy.
2. Verify anonymous writes return 401 and public reads remain available.
3. Deploy the code containing the dual-header cron client.
4. Configure both cron secrets and `PARO_BASE_URL`.
5. Run once manually, then enable the schedule.
6. Observe two consecutive runs and reconcile API, database, dashboard, and
   logs before calling the feed ready.
