# Architecture Overview

GridRate has two halves: a **pure-Python rate engine** (`api/`, no Home
Assistant imports) and the **Home Assistant integration** around it
(coordinators, entities, flows).

## Directory structure

```text
custom_components/gridrate/
├── api/                         # Pure Python — no homeassistant imports
│   ├── tariff/
│   │   ├── models.py            # Tariff, TariffVersion, Season, TouWindow,
│   │   │                        #   EnergyComponent, PercentSurcharge,
│   │   │                        #   BaselinePolicy, FixedCharge
│   │   ├── engine.py            # marginal_rate(), compute_bill() (golden-
│   │   │                        #   bill replay), season/period resolution
│   │   ├── schema.py            # JSON (de)serialization + validation;
│   │   │                        #   load_shipped_plan()
│   │   └── plans/               # pge_e_tou_c.json, cleanpowersf_e_tou_c3.json
│   └── derivation.py            # derive() tariff params from hourly reads;
│                                #   drift_report(); apply_drift_fixes()
├── coordinator/
│   ├── opower.py                # Ported from core opower (see NOTICE):
│   │                            #   12h polling, external statistics under
│   │                            #   gridrate:, retains cost reads
│   └── realtime.py              # 1-min tariff evaluation + meter-driven
│                                #   cost accrual, Store persistence, cycle
│                                #   bounds from the utility forecast
├── config_flow_handler/
│   ├── config_flow.py           # Utility select + credentials + MFA + reauth
│   └── options_flow.py          # Tariff plan + meter entity selection
├── sensor/
│   ├── __init__.py              # Utility-account bill sensors (ported)
│   └── realtime.py              # Rate-engine sensors (current_rate, costs…)
├── binary_sensor/               # peak_period, over_baseline
├── drift.py                     # Re-derive after each refresh; raise repair
├── repairs.py                   # unsupported_utility + tariff_drift fixes
├── diagnostics.py               # Redacted config/account/forecast dump
└── translations/en.json
```

## Data flow

```text
Opower API ──(12h)──> GridRateOpowerCoordinator
    │                     ├── bill sensors (per-account devices)
    │                     ├── external statistics (gridrate: prefix)
    │                     ├── cost reads ──> drift.py ──> repair issue
    │                     └── forecast (cycle start/end dates)
    │                                            │
Local meter entity ──(state events)──> GridRateRealtimeCoordinator
                                          │   (tariff stack from options:
                                          │    shipped plans or drift override)
                                          └── rate/cost entities
```

Key invariants:

- Everything in `api/` is deterministic, Decimal-based math with fast unit
  tests; the golden test replays a real PG&E+CleanPowerSF bill to the cent.
- The realtime coordinator never scrapes sensor states for cycle boundaries —
  it reads the `Forecast` on the opower coordinator directly.
- Statistics IDs are `gridrate:`-prefixed so GridRate can run side by side
  with core `opower` during migration.
- Times given to the tariff engine are naive utility-local wall time; the
  integration assumes the Home Assistant timezone matches the utility's.

## Testing

- `tests/unit/` — pure engine/derivation tests (no HA fixtures; run in ms).
- `tests/integration/` — `pytest-homeassistant-custom-component` tests with
  a mocked Opower client and recorder (`recorder_mock` must be requested
  before `hass`; see `tests/integration/conftest.py`).

See [DECISIONS.md](DECISIONS.md) for the reasoning behind the architecture.
