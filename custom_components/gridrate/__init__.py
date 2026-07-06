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

from custom_components.gridrate.const import CONF_UTILITY, DOMAIN
from custom_components.gridrate.coordinator import GridRateOpowerCoordinator
from custom_components.gridrate.data import GridRateData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.gridrate.data import GridRateConfigEntry

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GridRateConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: GridRateConfigEntry) -> None:
    """Reload a config entry after its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
