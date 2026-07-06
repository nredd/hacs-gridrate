"""Repairs for GridRate.

The unsupported-utility fix flow is ported from Home Assistant core's
``opower`` integration (Apache-2.0, by @tronikos — see NOTICE).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.repairs import RepairsFlow

if TYPE_CHECKING:
    from homeassistant.components.repairs import RepairsFlowResult
    from homeassistant.core import HomeAssistant


class UnsupportedUtilityFixFlow(RepairsFlow):
    """Handler for removing a config entry that uses an unsupported utility."""

    def __init__(self, data: dict[str, str]) -> None:
        """Initialize."""
        self._entry_id = data["entry_id"]
        self._placeholders = data.copy()
        self._placeholders.pop("entry_id")

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,  # noqa: ARG002 - signature fixed by the base class
    ) -> RepairsFlowResult:
        """Handle the first step of a fix flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Handle the confirm step of a fix flow."""
        if user_input is not None:
            await self.hass.config_entries.async_remove(self._entry_id)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="confirm", description_placeholders=self._placeholders
        )


async def async_create_fix_flow(
    hass: HomeAssistant,  # noqa: ARG001 - signature fixed by Home Assistant
    issue_id: str,
    data: dict[str, str] | None,
) -> RepairsFlow:
    """Create a fix flow for a repair issue."""
    if not issue_id.startswith("unsupported_utility") or data is None:
        msg = f"unexpected repair issue {issue_id!r}"
        raise ValueError(msg)
    return UnsupportedUtilityFixFlow(data)
