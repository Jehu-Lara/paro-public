# PARO Power BI dashboard

PBIP project (`dashboard_oee.pbip`) connecting to the two Neon analytics
views (`fact_downtime_event`, `production_record`) that `docs/analytics.md`
documents. Open `dashboard_oee.pbip` in Power BI Desktop.

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
