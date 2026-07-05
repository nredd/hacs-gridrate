# Architectural Decision Records

Decisions that shaped GridRate, in the spirit of
[ADRs](https://adr.github.io/). Newest last.

## ADR-001: Custom component, not helpers/templates

**Status:** Accepted

**Context:** Real-time bill-accurate cost could be assembled from template
sensors, helpers, and automations on top of the core `opower` integration.
That sprawl is fragile (a dozen interdependent YAML/UI objects), hard to
maintain, and impossible to share with other users.

**Decision:** Ship a self-contained HACS custom component with a native rate
engine, native entities, and zero required helpers/templates/automations.

**Consequences:** More upfront work; a reusable, testable, shareable result
with golden-bill regression tests.

## ADR-002: Subsume core opower rather than depend on it

**Status:** Accepted

**Context:** GridRate needs the utility's billed usage/cost (source of truth
for calibration) *and* its own rate engine. Depending on the core `opower`
integration would mean scraping its sensors/statistics and living with its
entity model; core integrations also can't be extended by custom components.

**Decision:** Port the core `opower` coordinator/sensors/config-flow
(Apache-2.0, attributed in NOTICE) into GridRate, writing statistics under the
`gridrate:` prefix, and use the `opower` PyPI library directly for utility
access. Users run GridRate *instead of* core opower.

**Consequences:** ~1,000 lines ported and now owned here (tracked against
upstream); in exchange the coordinator's hourly reads directly feed rate
derivation, and bill-cycle boundaries flow to the realtime coordinator without
sensor-state scraping.

## ADR-003: Link to the real provider, not public tariff databases

**Status:** Accepted

**Context:** Public tariff databases (e.g. URDB-derived JSON) ship static,
often stale rate tables, make users hand-pick their tier, and have no CCA
(community choice aggregation) support — the largest source of real-world
error for CCA customers.

**Decision:** Treat the utility's own billed data (via Opower) as ground
truth. Ship curated tariff definitions (with effective dates) as *starting
points*, and continuously re-derive delivery rates, TOU windows, baseline
credit/allowance, and cycle boundaries from the utility's hourly cost÷usage
statistics. When the derived tariff drifts from the configured one, raise a
Repair with a one-click apply.

**Consequences:** Rates self-heal after utility rate changes; the shipped
definitions only need to be roughly right.

## ADR-004: Pure-Python `api/` layer with no Home Assistant imports

**Status:** Accepted (inherited from the blueprint template)

**Context:** The tariff engine and derivation logic are deterministic math
that benefits from fast, HA-free unit tests (golden bill replays).

**Decision:** Everything under `custom_components/gridrate/api/` (tariff
models/engine/schema, derivation, opower client wrapper) is pure Python with
no `homeassistant` imports. HA-facing code lives in `coordinator/`, platform
packages, and `config_flow_handler/`.

**Consequences:** The strongest correctness tests (bill replay) run in
milliseconds without the HA test harness.
