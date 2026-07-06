"""Tests for the ported utility-account bill sensors."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_elec_bill_sensors_created(
    setup_entry: Callable[..., Awaitable[MockConfigEntry]],
    hass: HomeAssistant,
) -> None:
    """An ELEC account with a kWh forecast exposes the electric bill sensors."""
    await setup_entry()

    states = {
        state.entity_id: state
        for state in hass.states.async_all("sensor")
        if "elec_account_111111" in state.entity_id
    }
    assert states, "no utility account sensors were created"

    cost = states["sensor.elec_account_111111_current_bill_electric_cost_to_date"]
    assert float(cost.state) == 75.5
    assert cost.attributes["unit_of_measurement"] == "USD"

    usage = states["sensor.elec_account_111111_current_bill_electric_usage_to_date"]
    assert float(usage.state) == 180.0
    assert usage.attributes["unit_of_measurement"] == "kWh"

    forecast = states["sensor.elec_account_111111_current_bill_electric_forecasted_cost"]
    assert float(forecast.state) == 88.0
