# PARO Power BI dashboard

PBIP project (`dashboard_oee.pbip`) with two views:

- **Live OEE Overview** imports the public
  `/api/v1/demo/overview` read model. OEE, Availability, Performance and
  Quality arrive already computed by Python. The small DAX measures only
  select the single imported value; they do not rebuild an OEE formula.
- **Historical Facts** keeps the Neon `fact_downtime_event` and
  `production_record` analytical views documented in `docs/analytics.md`.

Open `dashboard_oee.pbip` in Power BI Desktop and refresh after the matching
API branch has been deployed. The API route returning 404/503 is a deployment
or data-readiness failure, not a reason to replace the source with mock values.

See [`how-this-was-built.md`](../how-this-was-built.md) for how
this project (including this dashboard) was built and reviewed.

## Applying `paro-theme.json`

**View → Themes → Browse for themes...** → select `paro-theme.json`.

This **copies** the theme's contents into the report at import time — the
`.json` file in this folder is a one-time source, not a live link. Editing
`paro-theme.json` later and expecting an already-open report to pick up the
change does nothing; you have to re-import it (same menu path) after any
future edit to the source file for the report to reflect it.

## Local-only files (gitignored)

`*/.pbi/cache.abf` (semantic model's binary cache) and
`*/.pbi/localSettings.json` (a DPAPI-encrypted blob tied to the Windows
account that opened the project — likely related to the Neon data-source
credentials) are excluded from version control. Neither is source; the
latter shouldn't be published regardless of what's in it.

## Validation gate

Run `powerbi-report-author validate dashboard_oee.Report` before review, then
reload and refresh in Power BI Desktop. A PBIR schema pass does not substitute
for Desktop render verification. Publish to web is intentionally not used.
