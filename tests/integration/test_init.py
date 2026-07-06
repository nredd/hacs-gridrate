"""Tests for GridRate config entry setup and unload."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntryState

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_setup_and_unload_entry(
    setup_entry: Callable[..., Awaitable[MockConfigEntry]],
    hass: HomeAssistant,
) -> None:
    """A config entry sets up, exposes runtime data, and unloads cleanly."""
    entry = await setup_entry()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
