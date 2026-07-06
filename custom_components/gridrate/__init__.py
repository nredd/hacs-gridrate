"""The GridRate integration.

Connects to a utility account via Opower for billed usage/cost data, evaluates
the account's real tariff (time-of-use windows, baseline tiers, CCA generation,
fixed charges) against a local energy meter, and exposes bill-accurate
real-time electricity pricing and cost as Home Assistant entities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.helpers import issue_registry as ir
import homeassistant.helpers.config_validation as cv
from homeassistant.loader import async_get_loaded_integration
from opower import select_utility

from custom_components.gridrate.api.tariff import Tariff, load_shipped_plan
from custom_components.gridrate.const import (
    CONF_DELIVERY_PLAN,
    CONF_GENERATION_PLAN,
    CONF_METER_ENTITY,
    CONF_UTILITY,
    DOMAIN,
    LOGGER,
    PLAN_NONE,
)
from custom_components.gridrate.coordinator import (
    GridRateOpowerCoordinator,
    GridRateRealtimeCoordinator,
)
from custom_components.gridrate.data import GridRateData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.gridrate.data import GridRateConfigEntry

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _load_tariff_stack(entry: GridRateConfigEntry) -> list[Tariff]:
    """Load the tariff stack selected in the entry options."""
    stack: list[Tariff] = []
    for option in (CONF_DELIVERY_PLAN, CONF_GENERATION_PLAN):
        plan_id = entry.options.get(option)
        if not plan_id or plan_id == PLAN_NONE:
            continue
        try:
            stack.append(load_shipped_plan(plan_id))
        except ValueError:
            LOGGER.error("Unknown tariff plan %r in options; skipping", plan_id)
    return stack


async def async_setup_entry(hass: HomeAssistant, entry: GridRateConfigEntry) -> bool:
    """Set up a GridRate utility account from a config entry."""
    utility_name = entry.data[CONF_UTILITY]
    try:
        select_utility(utility_name)
    except ValueError:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"unsupported_utility_{entry.entry_id}",
            is_fixable=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="unsupported_utility",
            translation_placeholders={"utility": utility_name},
            data={
                "entry_id": entry.entry_id,
                "utility": utility_name,
                "title": entry.title,
            },
        )
        return False

    coordinator = GridRateOpowerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = GridRateData(
        opower_coordinator=coordinator,
        integration=async_get_loaded_integration(hass, entry.domain),
    )

    if tariffs := _load_tariff_stack(entry):
        realtime = GridRateRealtimeCoordinator(
            hass,
            entry,
            tariffs,
            coordinator,
            entry.options.get(CONF_METER_ENTITY),
        )
        await realtime.async_setup()
        await realtime.async_config_entry_first_refresh()
        entry.runtime_data.realtime_coordinator = realtime

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GridRateConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: GridRateConfigEntry) -> None:
    """Reload a config entry after its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
