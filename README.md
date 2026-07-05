# GridRate for Home Assistant

A fully native Home Assistant integration for **real utility rate plans** —
bill-accurate, real-time electricity pricing and cost tracking. GridRate signs
in to your utility (via [Opower](https://github.com/tronikos/opower), the
platform behind ~40 US utilities including PG&E), pulls your billed usage and
cost, and evaluates your *actual tariff* — time-of-use windows, seasonal rates,
baseline tiers, CCA generation charges, flat adders, and fixed daily charges —
against a local energy meter so you can see what electricity really costs you
**right now**, not two days from now.

GridRate subsumes the core `opower` integration (same billed statistics,
compatible with the Energy dashboard) and adds a native rate engine on top.

## Why

- **Utility cost data lags ~2 days** and (for CCA customers) covers only the
  utility's delivery charges — it can understate your true marginal cost by
  25% or more.
- Public tariff databases ship stale, tierless rate tables and don't model CCA
  generation at all.
- Your bill is fully deterministic: given your tariff and your meter, the cost
  is computable in real time. GridRate computes it.

## Features

- **Everything core `opower` provides**: bill usage/cost to date, forecasts,
  typical usage/cost, bill cycle dates, and external statistics for the Energy
  dashboard (consumption, return, cost, compensation).
- **`sensor.gridrate_current_rate`** — your full marginal $/kWh right now, with
  a component breakdown (delivery / generation / adders / baseline credit),
  current tier, TOU period, and season as attributes, plus `raw_today` /
  `raw_tomorrow` hourly price arrays (Nordpool-compatible shape) for
  evcc/EMHASS interop. Use it as the Energy dashboard's "entity with current
  price".
- **Real-time cost accrual** from a local meter entity: cost today, billing
  cycle cost (including prorated fixed charges), and a projected bill.
- **Baseline/tier tracking**: billing-cycle usage, baseline allowance
  remaining, over-baseline and peak-period binary sensors, next period change.
- **Self-calibration**: GridRate derives your delivery rates, TOU windows,
  baseline credit/allowance, and billing cycle boundaries from your utility's
  own hourly cost/usage data — and raises a Repair with a one-click fix when
  your configured tariff drifts from what the utility is actually charging.

## Requirements

- A utility account served by Opower (PG&E validated; ~40 utilities supported
  for billed data).
- Optional but recommended: a local energy meter entity (whole-home kWh sensor,
  e.g. a Refoss/Shelly EM) for real-time cost.

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS (category: _Integration_).
2. Install **GridRate**.
3. Restart Home Assistant.

### Manual

Copy `custom_components/gridrate` into your Home Assistant
`config/custom_components/` directory and restart.

## Setup

Add it via **Settings → Devices & Services → Add Integration → GridRate**:
sign in with your utility credentials (MFA supported), pick your account,
select your local meter entity, and confirm the detected/prefilled tariff.
Shipped tariff definitions: PG&E E-TOU-C delivery + CleanPowerSF E-TOU-C3
generation (with effective dates). Everything is adjustable in the options
flow.

## Development

This project uses the [Astral](https://astral.sh) toolchain (`uv`, `ruff`, `ty`); `pyproject.toml`
is the single source of truth for dependencies and tooling.

```bash
uv sync --locked             # set up the environment
uv run ruff format --check . # formatting
uv run ruff check .          # lint
uv run ty check              # type-check
uv run pytest                # tests
```

`script/smoke` runs the full check + test suite, exactly as CI does. CI runs `script/smoke`
**inside the project's devcontainer image** (via [`devcontainers/ci`](https://github.com/devcontainers/ci)),
so local development and CI share one environment. Open the repo in the devcontainer (VS Code /
Codespaces) to get the same toolchain.

## Attribution

This integration was generated from the
[`jpawlowski/hacs.integration_blueprint`](https://github.com/jpawlowski/hacs.integration_blueprint)
template — a modernized Home Assistant integration blueprint, itself based on
[`ludeeus/integration_blueprint`](https://github.com/ludeeus/integration_blueprint).

The utility polling coordinator, credentials/MFA config flow, and bill sensors
are ported from Home Assistant core's Apache-2.0
[`opower` integration](https://www.home-assistant.io/integrations/opower/) by
[@tronikos](https://github.com/tronikos), which GridRate subsumes. Utility
authentication and data retrieval use the
[`opower`](https://github.com/tronikos/opower) library at runtime. See
[`NOTICE`](NOTICE) for details.

This project is not affiliated with or endorsed by any utility or by Opower/Oracle.
