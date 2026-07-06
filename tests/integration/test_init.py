"""Tests for GridRate config entry setup, unload, and statistics insertion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import get_last_statistics
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.gridrate.const import CONF_UTILITY, DOMAIN

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.core import HomeAssistant

CONSUMPTION_STAT_ID = "gridrate:pge_elec_111111_energy_consumption"
COST_STAT_ID = "gridrate:pge_elec_111111_energy_cost"


async def test_setup_and_unload_entry(
    setup_entry: Callable[..., Awaitable[MockConfigEntry]],
    hass: HomeAssistant,
) -> None:
    """A config entry sets up, exposes runtime data, and unloads cleanly."""
    entry = await setup_entry()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.opower_coordinator.data is not None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_external_statistics_inserted(
    setup_entry: Callable[..., Awaitable[MockConfigEntry]],
    hass: HomeAssistant,
) -> None:
    """Cost and consumption statistics are written under the gridrate: prefix."""
    await setup_entry()
    await async_wait_recording_done(hass)

    stats = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, CONSUMPTION_STAT_ID, True, {"sum"}
    )
    # 48 hourly reads x 0.5 kWh.
    assert stats[CONSUMPTION_STAT_ID][0]["sum"] == 24.0

    stats = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, COST_STAT_ID, True, {"sum"}
    )
    # 48 hourly reads x $0.20.
    assert stats[COST_STAT_ID][0]["sum"] == pytest.approx(9.60)


async def test_cost_reads_retained_for_derivation(
    setup_entry: Callable[..., Awaitable[MockConfigEntry]],
) -> None:
    """The coordinator keeps the fetched cost reads on each account's data."""
    entry = await setup_entry()
    data = entry.runtime_data.opower_coordinator.data["111111"]
    assert len(data.cost_reads) == 48
    assert data.forecast is not None
    assert data.forecast.cost_to_date == 75.5


async def test_unsupported_utility_creates_issue(
    recorder_mock,
    hass: HomeAssistant,
) -> None:
    """An entry with an unsupported utility fails setup and raises an issue."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_UTILITY: "No Such Utility", "username": "u", "password": "p"},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    registry = ir.async_get(hass)
    assert any(
        issue.issue_id.startswith("unsupported_utility")
        for issue in registry.issues.values()
        if issue.domain == DOMAIN
    )
