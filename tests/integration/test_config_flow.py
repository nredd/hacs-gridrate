"""Tests for the GridRate config flow (utility select, credentials, errors)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from opower.exceptions import CannotConnect, InvalidAuth
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gridrate.const import CONF_UTILITY, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant

UTILITY_NAME = "Pacific Gas and Electric Company (PG&E)"


async def _start_credentials_step(hass: HomeAssistant) -> ConfigFlowResult:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_UTILITY: UTILITY_NAME}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "credentials"
    return result


async def test_user_flow_creates_entry(
    recorder_mock,
    hass: HomeAssistant,
    mock_opower_api: MagicMock,
) -> None:
    """Utility select -> credentials -> entry created."""
    result = await _start_credentials_step(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "password"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"{UTILITY_NAME} (user@example.com)"
    assert result["data"][CONF_UTILITY] == UTILITY_NAME
    mock_opower_api.async_login.assert_awaited()


async def test_invalid_auth_shows_error(
    recorder_mock,
    hass: HomeAssistant,
    mock_opower_api: MagicMock,
) -> None:
    """A login failure keeps the user on the credentials form with an error."""
    mock_opower_api.async_login.side_effect = InvalidAuth("bad password")
    result = await _start_credentials_step(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "wrong"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_cannot_connect_shows_error(
    recorder_mock,
    hass: HomeAssistant,
    mock_opower_api: MagicMock,
) -> None:
    """A connection failure keeps the user on the credentials form."""
    mock_opower_api.async_login.side_effect = CannotConnect("offline")
    result = await _start_credentials_step(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "password"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_duplicate_account_aborts(
    recorder_mock,
    hass: HomeAssistant,
    mock_opower_api: MagicMock,
) -> None:
    """Configuring the same utility+username twice aborts."""
    MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_UTILITY: UTILITY_NAME,
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "password",
        },
    ).add_to_hass(hass)

    result = await _start_credentials_step(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "password"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
