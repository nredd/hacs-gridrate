"""Repairs for GridRate.

Two fix flows:

- ``unsupported_utility`` — remove an entry whose utility the opower library
  no longer supports (ported from core opower; Apache-2.0, @tronikos, see
  NOTICE).
- ``tariff_drift`` — the utility's actual rates (derived from its own hourly
  billed data) diverged from the configured tariff; one click applies the
  derived values as a delivery-tariff override on the config entry.
"""

from __future__ import annotations

from datetime import date
import json
from typing import TYPE_CHECKING, Any

from homeassistant.components.repairs import RepairsFlow

from custom_components.gridrate.api.derivation import apply_drift_fixes
from custom_components.gridrate.api.tariff import load_shipped_plan, tariff_to_dict
from custom_components.gridrate.const import CONF_DELIVERY_OVERRIDE, CONF_DELIVERY_PLAN
from custom_components.gridrate.drift import ISSUE_PREFIX

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


class TariffDriftFixFlow(RepairsFlow):
    """Apply utility-derived tariff values as a config-entry override."""

    def __init__(self, data: dict[str, Any]) -> None:
        """Initialize from the issue data written by the drift check."""
        self._entry_id: str = data["entry_id"]
        self._season: str = data["season"]
        self._effective_on = date.fromisoformat(data["effective_on"])
        self._fixes: dict[str, str] = json.loads(data["fixes"])

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,  # noqa: ARG002 - signature fixed by the base class
    ) -> RepairsFlowResult:
        """Handle the first step of a fix flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Confirm and apply the derived tariff values."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_removed")

        if user_input is not None:
            base = entry.options.get(CONF_DELIVERY_OVERRIDE) or tariff_to_dict(
                load_shipped_plan(entry.options[CONF_DELIVERY_PLAN])
            )
            patched = apply_drift_fixes(
                base, self._season, self._effective_on, self._fixes
            )
            self.hass.config_entries.async_update_entry(
                entry,
                options={**entry.options, CONF_DELIVERY_OVERRIDE: patched},
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "details": "\n".join(
                    f"- `{field}` → {value}" for field, value in self._fixes.items()
                ),
                "season": self._season,
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant,  # noqa: ARG001 - signature fixed by Home Assistant
    issue_id: str,
    data: dict[str, str] | None,
) -> RepairsFlow:
    """Create a fix flow for a repair issue."""
    if data is None:
        msg = f"repair issue {issue_id!r} has no data"
        raise ValueError(msg)
    if issue_id.startswith(ISSUE_PREFIX):
        return TariffDriftFixFlow(data)
    if issue_id.startswith("unsupported_utility"):
        return UnsupportedUtilityFixFlow(data)
    msg = f"unexpected repair issue {issue_id!r}"
    raise ValueError(msg)
