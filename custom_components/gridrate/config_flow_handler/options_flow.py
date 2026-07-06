"""Options flow for the GridRate integration.

Configures the rate engine: which shipped tariff plans to stack (delivery +
generation) and which local energy meter entity feeds realtime cost accrual.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import OptionsFlow
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from custom_components.gridrate.api.tariff import shipped_plan_ids
from custom_components.gridrate.const import (
    CONF_DELIVERY_PLAN,
    CONF_GENERATION_PLAN,
    CONF_METER_ENTITY,
    PLAN_NONE,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult


class GridRateOptionsFlowHandler(OptionsFlow):
    """Handle the GridRate options flow (rate engine configuration)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure tariff plans and the local meter entity."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        plan_options = [PLAN_NONE, *shipped_plan_ids()]
        plan_selector = SelectSelector(
            SelectSelectorConfig(
                options=plan_options,
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="tariff_plan",
            )
        )
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DELIVERY_PLAN,
                    default=options.get(CONF_DELIVERY_PLAN, PLAN_NONE),
                ): plan_selector,
                vol.Required(
                    CONF_GENERATION_PLAN,
                    default=options.get(CONF_GENERATION_PLAN, PLAN_NONE),
                ): plan_selector,
                vol.Optional(
                    CONF_METER_ENTITY,
                    description={"suggested_value": options.get(CONF_METER_ENTITY)},
                ): EntitySelector(
                    EntitySelectorConfig(
                        domain="sensor",
                        device_class=SensorDeviceClass.ENERGY,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
