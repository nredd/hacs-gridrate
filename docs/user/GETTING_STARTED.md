# Getting Started

GridRate connects to your utility account (via Opower, the platform behind
~40 US utilities including PG&E), pulls your billed usage/cost, and evaluates
your real tariff against a local energy meter for bill-accurate, real-time
electricity pricing.

## Requirements

- A utility account served by Opower (PG&E validated end to end).
- Home Assistant 2026.6 or newer.
- Optional but recommended: a whole-home energy meter entity in kWh (e.g. a
  Refoss EM16 / Shelly EM mains sensor). Without one you still get the live
  rate and TOU entities, but not realtime cost accrual.

> **Replacing core opower:** GridRate subsumes the core `opower` integration
> — same bill sensors, same external statistics (under the `gridrate:`
> prefix). Run both side by side while validating, then remove the core
> `opower` entry to avoid double API polling.

## Installation

### HACS (recommended)

1. HACS → three-dot menu → **Custom repositories** → add this repository
   (category: _Integration_).
2. Install **GridRate** and restart Home Assistant.

### Manual

Copy `custom_components/gridrate` into `config/custom_components/` and
restart.

## Setup

1. **Settings → Devices & Services → Add Integration → GridRate.**
2. Select your utility, then sign in with your utility credentials. MFA is
   supported (select a method and enter the code; some utilities accept a
   TOTP secret instead).
3. Open the entry's **Configure** (options) to enable the rate engine:
   - **Delivery tariff** — your utility's rate plan (shipped:
     `PG&E E-TOU-C delivery (Baseline Territory T)`).
   - **Generation tariff** — your CCA's plan if you have one (shipped:
     `CleanPowerSF E-TOU-C3 generation`); otherwise **None**.
   - **Local energy meter** — your whole-home kWh sensor.

The bill sensors and statistics appear immediately; realtime cost entities
appear once a tariff and meter are configured.

## Energy dashboard

- **Grid consumption** → your local meter (or the
  `gridrate:..._energy_consumption` statistic for billed actuals).
- **Use an entity with current price** → `sensor.gridrate_current_rate`.

Cost then accrues in the Energy dashboard same-day at your true marginal
rate, instead of two days late.

## Self-calibration

After every utility refresh, GridRate re-derives your delivery rates, TOU
windows, baseline credit, and allowance from the utility's own hourly billed
data. If the utility changes rates, a **Repair** appears with the derived
values and a one-click apply.
