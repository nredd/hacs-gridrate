"""Shared pytest fixtures for the GridRate integration tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gridrate.const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.core import HomeAssistant


# NOTE: ``recorder_mock`` is requested before ``enable_custom_integrations``
# (which pulls in ``hass``): the integration declares ``recorder`` as a manifest
# dependency for external statistics, and pytest-homeassistant-custom-component
# asserts the recorder database is initialized before hass is created.
@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Set up the recorder and enable the custom integration in every test."""
    return


@pytest.fixture
def setup_entry(hass: HomeAssistant) -> Callable[..., Awaitable[MockConfigEntry]]:
    """Return a factory that sets up a GridRate config entry."""

    async def _setup() -> MockConfigEntry:
        entry = MockConfigEntry(domain=DOMAIN, data={})
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _setup
