# Illustrative ROI model

This is a planning model, not evidence of savings achieved by PARO or by a
client. All values are editable assumptions in USD. Avoided downtime and scrap
benefits default to zero until a client supplies verified minutes, margin, and
realization data.

## Formula

```text
gross_hours = reports_per_week * 52 * manual_hours_per_report
realized_benefit = gross_hours * loaded_hourly_rate * realization_factor
year_1_cost = implementation_cost + annual_operations
year_1_net = realized_benefit - year_1_cost
roi = year_1_net / year_1_cost
payback_months = implementation_cost / (realized_benefit - annual_operations) * 12
```

Payback is undefined when realized benefit does not exceed annual operations.

## Shared assumptions

| Assumption | Value | Basis |
|---|---:|---|
| Reports per week | 5 | Illustrative weekday reporting cadence |
| One-time implementation | $3,500 | Illustrative project cost |
| Annual operations | $600 | Illustrative maintenance/training allowance; includes the $12/year minimum for the selected Render cron |
| Avoided downtime/scrap | $0 | Deliberately excluded without verified client economics |

## Scenarios

| Scenario | Manual hours/report | Loaded rate | Realization | Gross hours | Benefit | Year-1 net | ROI | Payback |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Conservative | 0.25 | $45 | 50% | 65 | $1,462.50 | -$2,637.50 | -64.3% | 48.7 months |
| Base | 0.50 | $55 | 70% | 130 | $5,005.00 | $905.00 | 22.1% | 9.5 months |
| Upside | 1.00 | $70 | 80% | 260 | $14,560.00 | $10,460.00 | 255.1% | 3.0 months |

## Sensitivity and use

- Replace reporting cadence, time, loaded rate, realization, implementation,
  and annual operations with client-approved inputs before using this model in
  a proposal.
- Keep downtime and scrap at zero unless source data and contribution margin
  can be reconciled.
- Always show the conservative case, including its negative ROI. Do not present
  the base or upside case as a forecast or guarantee.
