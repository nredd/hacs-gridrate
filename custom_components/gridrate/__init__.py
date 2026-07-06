"""The GridRate integration.

Connects to a utility account via Opower for billed usage/cost data, evaluates
the account's real tariff (time-of-use windows, baseline tiers, CCA generation,
fixed charges) against a local energy meter, and exposes bill-accurate
real-time electricity pricing and cost as Home Assistant entities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.helpers import issue_registry as ir
import homeassistant.helpers.config_validation as cv
from homeassistant.loader import async_get_loaded_integration
from opower import select_utility

from custom_components.gridrate.api.tariff import (
    Tariff,
    load_shipped_plan,
    tariff_from_dict,
)
from custom_components.gridrate.const import (
    CONF_DELIVERY_OVERRIDE,
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
from custom_components.gridrate.drift import async_check_drift

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.gridrate.data import GridRateConfigEntry

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _load_tariffs(entry: GridRateConfigEntry) -> tuple[Tariff | None, Tariff | None]:
    """Load the (delivery, generation) tariffs selected in the entry options.

    A drift-repair override (``CONF_DELIVERY_OVERRIDE``, the JSON-mapping form
    of a tariff) takes precedence over the shipped delivery plan.
    """
    loaded: dict[str, Tariff | None] = {}
    for option in (CONF_DELIVERY_PLAN, CONF_GENERATION_PLAN):
        loaded[option] = None
        plan_id = entry.options.get(option)
        if not plan_id or plan_id == PLAN_NONE:
            continue
        try:
            loaded[option] = load_shipped_plan(plan_id)
        except ValueError:
            LOGGER.error("Unknown tariff plan %r in options; skipping", plan_id)

    if override := entry.options.get(CONF_DELIVERY_OVERRIDE):
        try:
            loaded[CONF_DELIVERY_PLAN] = tariff_from_dict(override)
        except ValueError:
            LOGGER.exception("Invalid delivery tariff override; using shipped plan")

    return loaded[CONF_DELIVERY_PLAN], loaded[CONF_GENERATION_PLAN]


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

    delivery, generation = _load_tariffs(entry)
    if tariffs := [tariff for tariff in (delivery, generation) if tariff is not None]:
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

    if delivery is not None:
        # Re-check tariff drift after every utility refresh.
        drift_delivery = delivery

        @callback
        def _drift_listener() -> None:
            async_check_drift(hass, entry, drift_delivery)

        entry.async_on_unload(coordinator.async_add_listener(_drift_listener))
        _drift_listener()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GridRateConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: GridRateConfigEntry) -> None:
    """Reload a config entry after its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
