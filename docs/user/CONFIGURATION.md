# Configuration Reference

## Entities

### Utility account device (per account, ported from core opower)

| Entity                                        | Description                              |
| --------------------------------------------- | ---------------------------------------- |
| `sensor.…_current_bill_electric_usage_to_date` | Billed kWh so far this cycle             |
| `sensor.…_current_bill_electric_cost_to_date`  | Utility's billed cost so far (delivery)  |
| `sensor.…_current_bill_electric_forecasted_*`  | Utility's usage/cost forecast            |
| `sensor.…_typical_monthly_electric_*`          | Typical usage/cost                       |
| `sensor.…_current_bill_electric_start/end_date`| Billing cycle bounds (disabled default)  |
| `sensor.…_last_changed` / `…_last_updated`     | Data freshness diagnostics               |

Plus four external statistics per account for the Energy dashboard:
`gridrate:<utility>_<type>_<account>_energy_{consumption,return,cost,compensation}`.

### GridRate rate engine device (per entry, needs a tariff configured)

| Entity                               | Needs meter | Description                                             |
| ------------------------------------ | ----------- | ------------------------------------------------------- |
| `sensor.gridrate_current_rate`       | no          | Full marginal $/kWh right now                            |
| `sensor.gridrate_next_period_change` | no          | When the TOU period next flips                           |
| `binary_sensor.gridrate_peak_period` | no          | On during the peak window                                |
| `sensor.gridrate_billing_cycle_usage`| yes         | kWh accrued this billing cycle                           |
| `sensor.gridrate_baseline_remaining` | yes         | kWh left before tier 2                                   |
| `binary_sensor.gridrate_over_baseline`| yes        | On once cycle usage exceeds the baseline allowance       |
| `sensor.gridrate_cost_today`         | yes         | Today's cost (energy + prorated fixed charge)            |
| `sensor.gridrate_billing_cycle_cost` | yes         | Cycle-to-date cost                                       |
| `sensor.gridrate_projected_bill`     | yes         | Simple projection to cycle end                           |

### `sensor.gridrate_current_rate` attributes

- `components` — $/kWh breakdown: delivery, generation, adders/credits,
  baseline credit, percent surcharges.
- `season`, `period`, `tier`, `over_baseline`, `cycle_start`, `cycle_end`.
- `raw_today` / `raw_tomorrow` — hourly `{start, end, value}` price arrays
  (Nordpool-compatible shape) for evcc/EMHASS/charts.

## Options

| Option            | Meaning                                                              |
| ----------------- | -------------------------------------------------------------------- |
| Delivery tariff   | Shipped delivery plan (`pge_e_tou_c`) or None                        |
| Generation tariff | Shipped CCA generation plan (`cleanpowersf_e_tou_c3`) or None        |
| Local energy meter| kWh sensor for realtime accrual (handles daily-reset sensors)        |

A drift repair, when applied, stores a corrected copy of the delivery tariff
in the entry options (`delivery_override`); it takes precedence over the
shipped plan until you clear it by re-saving options.

## Tariff definitions

Shipped plans live in `custom_components/gridrate/api/tariff/plans/*.json`:
dated versions with seasons, TOU windows, per-kWh components (delivery /
generation / adders), percent surcharges, a baseline policy, and fixed daily
charges. All money values are strings (parsed as exact decimals).
Contributions of additional utility plans are welcome.
