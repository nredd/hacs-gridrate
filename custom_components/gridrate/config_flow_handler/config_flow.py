"""Config flow for the GridRate integration.

Placeholder: the utility credentials/MFA steps (ported from the core opower
integration) and the local meter/tariff steps land with the coordinator port.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigFlow

from custom_components.gridrate.const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult


class GridRateConfigFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for GridRate utility accounts."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002 - form input unused until the flow is implemented
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        return self.async_abort(reason="not_implemented")
