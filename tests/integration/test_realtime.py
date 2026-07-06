"""Tests for the realtime rate/cost coordinator and its entities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gridrate.const import (
    CONF_DELIVERY_PLAN,
    CONF_GENERATION_PLAN,
    CONF_METER_ENTITY,
    DOMAIN,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from unittest.mock import MagicMock

    from homeassistant.core import HomeAssistant

METER = "sensor.test_mains_today_energy"

# 2026-07-04 10:00 local: summer, off-peak, tier 1 (no usage accrued yet).
# Full marginal rate from the shipped plans (see the unit engine tests).
SUMMER_OFFPEAK_T1_MIN = 0.35
SUMMER_OFFPEAK_T1_MAX = 0.36


@pytest.fixture
def setup_realtime_entry(
    hass: HomeAssistant,
    mock_opower_api: MagicMock,
    config_entry_data: dict[str, Any],
    freezer,
) -> Callable[..., Awaitable[MockConfigEntry]]:
    """Return a factory that sets up an entry with the rate engine enabled."""

    async def _setup() -> MockConfigEntry:
        freezer.move_to("2026-07-04 10:00:00-07:00")
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=config_entry_data,
            options={
                CONF_DELIVERY_PLAN: "pge_e_tou_c",
                CONF_GENERATION_PLAN: "cleanpowersf_e_tou_c3",
                CONF_METER_ENTITY: METER,
            },
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _setup


async def test_current_rate_and_period_entities(
    setup_realtime_entry: Callable[..., Awaitable[MockConfigEntry]],
    hass: HomeAssistant,
) -> None:
    """The rate sensor reports the summer off-peak tier-1 marginal rate."""
    await setup_realtime_entry()

    rate = hass.states.get("sensor.gridrate_current_rate")
    assert rate is not None
    assert SUMMER_OFFPEAK_T1_MIN < float(rate.state) < SUMMER_OFFPEAK_T1_MAX
    assert rate.attributes["season"] == "summer"
    assert rate.attributes["period"] == "off_peak"
    assert rate.attributes["tier"] == 1
    assert len(rate.attributes["raw_today"]) == 24
    assert len(rate.attributes["raw_tomorrow"]) == 24
    # Cycle bounds come from the mocked utility forecast.
    assert rate.attributes["cycle_start"] == "2026-06-05"
    assert rate.attributes["cycle_end"] == "2026-07-06"

    peak = hass.states.get("binary_sensor.gridrate_peak_period")
    assert peak is not None
    assert peak.state == "off"

    next_change = hass.states.get("sensor.gridrate_next_period_change")
    assert next_change is not None
    # Peak starts at 16:00 local.
    assert "16:00" in next_change.state or "23:00" in next_change.state


async def test_meter_accrual(
    setup_realtime_entry: Callable[..., Awaitable[MockConfigEntry]],
    hass: HomeAssistant,
) -> None:
    """Meter deltas accrue into today/cycle usage and cost."""
    await setup_realtime_entry()

    # First reading establishes the baseline; second accrues 2 kWh.
    hass.states.async_set(METER, "10.0")
    await hass.async_block_till_done()
    hass.states.async_set(METER, "12.0")
    await hass.async_block_till_done()

    usage = hass.states.get("sensor.gridrate_billing_cycle_usage")
    assert usage is not None
    assert float(usage.state) == pytest.approx(2.0)

    cost_today = hass.states.get("sensor.gridrate_cost_today")
    assert cost_today is not None
    # 2 kWh x ~0.355 $/kWh + prorated fixed charge (0.79343 x ~10/24 h).
    energy_cost = 2.0 * 0.3555
    fixed_prorated = 0.79343 * (10 / 24)
    assert float(cost_today.state) == pytest.approx(
        energy_cost + fixed_prorated, abs=0.05
    )

    cycle_cost = hass.states.get("sensor.gridrate_billing_cycle_cost")
    assert cycle_cost is not None
    # Cycle cost includes ~29 days of fixed charges since the cycle start.
    assert float(cycle_cost.state) > 20.0

    projected = hass.states.get("sensor.gridrate_projected_bill")
    assert projected is not None
    assert float(projected.state) > float(cycle_cost.state)


async def test_meter_reset_handled(
    setup_realtime_entry: Callable[..., Awaitable[MockConfigEntry]],
    hass: HomeAssistant,
) -> None:
    """A meter reset (daily-energy sensor) counts the new reading as delta."""
    await setup_realtime_entry()

    hass.states.async_set(METER, "10.0")
    await hass.async_block_till_done()
    hass.states.async_set(METER, "0.5")  # reset: 0.5 kWh since midnight
    await hass.async_block_till_done()

    usage = hass.states.get("sensor.gridrate_billing_cycle_usage")
    assert usage is not None
    assert float(usage.state) == pytest.approx(0.5)


async def test_baseline_tracking(
    setup_realtime_entry: Callable[..., Awaitable[MockConfigEntry]],
    hass: HomeAssistant,
) -> None:
    """Baseline remaining reflects the cycle allowance minus usage."""
    await setup_realtime_entry()

    remaining = hass.states.get("sensor.gridrate_baseline_remaining")
    assert remaining is not None
    # Cycle 2026-06-05..07-06 is fully in summer: (31+1) days x 7.1 kWh.
    assert float(remaining.state) == pytest.approx(32 * 7.1, abs=8)

    over = hass.states.get("binary_sensor.gridrate_over_baseline")
    assert over is not None
    assert over.state == "off"


async def test_no_realtime_entities_without_options(
    setup_entry: Callable[..., Awaitable[MockConfigEntry]],
    hass: HomeAssistant,
) -> None:
    """Without a tariff plan selected, no rate-engine entities exist."""
    await setup_entry()
    assert hass.states.get("sensor.gridrate_current_rate") is None
    assert hass.states.get("binary_sensor.gridrate_peak_period") is None
