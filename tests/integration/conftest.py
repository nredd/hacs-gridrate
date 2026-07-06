"""Shared pytest fixtures for the GridRate integration tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from opower import Account, CostRead, Forecast, MeterType, ReadResolution, UnitOfMeasure
from opower.opower import Customer
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gridrate.const import CONF_UTILITY, DOMAIN

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator

    from homeassistant.core import HomeAssistant

UTILITY_NAME = "Pacific Gas and Electric Company (PG&E)"
ACCOUNT_ID = "111111"
TZ = ZoneInfo("America/Los_Angeles")


# NOTE: ``recorder_mock`` is requested before ``enable_custom_integrations``
# (which pulls in ``hass``): the integration declares ``recorder`` as a manifest
# dependency for external statistics, and pytest-homeassistant-custom-component
# asserts the recorder database is initialized before hass is created.
@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Set up the recorder and enable the custom integration in every test."""
    return


def make_account() -> Account:
    """Return a PG&E electric account fixture."""
    return Account(
        customer=Customer(uuid="customer-uuid"),
        uuid="account-uuid",
        utility_account_id=ACCOUNT_ID,
        id="account-id",
        meter_type=MeterType.ELEC,
        read_resolution=ReadResolution.HOUR,
    )


def make_forecast(account: Account) -> Forecast:
    """Return a bill forecast fixture for the account."""
    return Forecast(
        account=account,
        start_date=date(2026, 6, 5),
        end_date=date(2026, 7, 6),
        current_date=date(2026, 7, 4),
        unit_of_measure=UnitOfMeasure.KWH,
        usage_to_date=180.0,
        cost_to_date=75.5,
        forecasted_usage=200.0,
        forecasted_cost=88.0,
        typical_usage=390.0,
        typical_cost=158.0,
    )


def make_cost_reads() -> list[CostRead]:
    """Return two days of hourly cost reads."""
    start = datetime(2026, 7, 2, 0, 0, tzinfo=TZ)
    return [
        CostRead(
            start_time=start + timedelta(hours=hour),
            end_time=start + timedelta(hours=hour + 1),
            consumption=0.5,
            provided_cost=0.2,
        )
        for hour in range(48)
    ]


@pytest.fixture
def mock_opower_api() -> Generator[MagicMock]:
    """Patch the Opower client class everywhere it is constructed."""
    account = make_account()
    api = MagicMock()
    api.async_login = AsyncMock()
    api.async_get_accounts = AsyncMock(return_value=[account])
    api.async_get_forecast = AsyncMock(return_value=[make_forecast(account)])
    api.async_get_cost_reads = AsyncMock(return_value=make_cost_reads())
    api.utility.subdomain.return_value = "pge"
    api.utility.timezone.return_value = "America/Los_Angeles"
    api.utility.name.return_value = UTILITY_NAME

    with (
        patch(
            "custom_components.gridrate.coordinator.opower.Opower",
            return_value=api,
        ),
        patch(
            "custom_components.gridrate.config_flow_handler.config_flow.Opower",
            return_value=api,
        ),
    ):
        yield api


@pytest.fixture
def config_entry_data() -> dict[str, Any]:
    """Return config entry data for a PG&E account."""
    return {
        CONF_UTILITY: UTILITY_NAME,
        CONF_USERNAME: "user@example.com",
        CONF_PASSWORD: "password",
    }


@pytest.fixture
def setup_entry(
    hass: HomeAssistant,
    mock_opower_api: MagicMock,
    config_entry_data: dict[str, Any],
) -> Callable[..., Awaitable[MockConfigEntry]]:
    """Return a factory that sets up a GridRate config entry."""

    async def _setup() -> MockConfigEntry:
        entry = MockConfigEntry(domain=DOMAIN, data=config_entry_data)
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _setup
