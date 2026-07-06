# Examples

## Energy dashboard with true realtime pricing

Settings → Dashboards → Energy:

1. **Grid consumption**: your local meter entity.
2. **Use an entity with current price**: `sensor.gridrate_current_rate`.

## Automations

### Precool / preheat before peak

```yaml
alias: Precool before peak
triggers:
  - trigger: time
    at: "15:30:00"
conditions:
  - condition: state
    entity_id: binary_sensor.gridrate_peak_period
    state: "off"
actions:
  - action: climate.set_temperature
    target:
      entity_id: climate.living_room
    data:
      temperature: 21
```

### Pause heavy loads during peak

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.gridrate_peak_period
    to: "on"
actions:
  - action: switch.turn_off
    target:
      entity_id: switch.ev_charger
```

### Warn when approaching the baseline allowance

```yaml
triggers:
  - trigger: numeric_state
    entity_id: sensor.gridrate_baseline_remaining
    below: 20
actions:
  - action: notify.mobile_app_phone
    data:
      message: >
        Only {{ states('sensor.gridrate_baseline_remaining') }} kWh of
        baseline left this cycle — marginal rate rises by ~8¢/kWh after.
```

## Dashboard cards

### Current rate with breakdown

```yaml
type: entities
entities:
  - entity: sensor.gridrate_current_rate
    name: Marginal rate now
  - entity: binary_sensor.gridrate_peak_period
  - entity: sensor.gridrate_next_period_change
  - entity: sensor.gridrate_cost_today
  - entity: sensor.gridrate_projected_bill
```

### Hourly price curve (ApexCharts)

```yaml
type: custom:apexcharts-card
header:
  title: Today's electricity price
series:
  - entity: sensor.gridrate_current_rate
    data_generator: |
      return entity.attributes.raw_today.map((p) => {
        return [new Date(p.start).getTime(), p.value];
      });
    type: area
    curve: stepline
```
