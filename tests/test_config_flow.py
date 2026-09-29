"""Tests for the config flow: setup, re-authentication and reconfiguration."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solaredge_hotwater.api import (
    AuthenticationError,
    LoginUnavailableError,
)
from custom_components.solaredge_hotwater.const import (
    CONF_DEVICE_ID,
    CONF_SITE_ID,
    DOMAIN,
)

from .common import (
    DEVICE_ID,
    DEVICE_NAME,
    ENTRY_DATA,
    add_config_entry,
    load_fixture,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant

USER_INPUT = {
    CONF_USERNAME: ENTRY_DATA[CONF_USERNAME],
    CONF_PASSWORD: ENTRY_DATA[CONF_PASSWORD],
    CONF_SITE_ID: ENTRY_DATA[CONF_SITE_ID],
}

SECOND_DEVICE_ID = "111111"
SECOND_DEVICE_NAME = "Zweiter Heizstab"

ERRORS = [
    (AuthenticationError, "invalid_auth"),
    (LoginUnavailableError, "cannot_connect"),
    (aiohttp.ClientError, "cannot_connect"),
    (TimeoutError, "cannot_connect"),
    (RuntimeError, "unknown"),
]


@pytest.fixture(autouse=True)
def setup_entry() -> Iterator[AsyncMock]:
    """Keep created and reloaded entries from setting up the integration."""
    with patch(
        "custom_components.solaredge_hotwater.async_setup_entry", return_value=True
    ) as setup_entry:
        yield setup_entry


@pytest.fixture
def api() -> Iterator[MagicMock]:
    """Patch the API client to answer with the recorded devices list."""
    with patch(
        "custom_components.solaredge_hotwater.config_flow.SolarEdgeWarmwaterAPI"
    ) as client:
        client.return_value.authenticate = AsyncMock(return_value=True)
        client.return_value.get_devices_info = AsyncMock(
            return_value=load_fixture("info.json")
        )
        yield client


def _two_devices() -> dict[str, Any]:
    """Return the recorded devices list with a second water heater."""
    devices = load_fixture("info.json")
    load_devices = devices["devicesByType"]["LOAD_DEVICE"]
    second = copy.deepcopy(load_devices[0])
    second["deviceInfo"]["deviceId"] = SECOND_DEVICE_ID
    second["deviceInfo"]["name"] = SECOND_DEVICE_NAME
    load_devices.append(second)
    return devices


async def _submit_user(hass: HomeAssistant) -> ConfigFlowResult:
    """Start the user flow and submit the credentials."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)


async def test_user_shows_the_form(hass: HomeAssistant) -> None:
    """Ask for username, password and site ID."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    assert list(result["data_schema"].schema) == list(USER_INPUT)


async def test_single_device_creates_the_entry(
    hass: HomeAssistant, api: MagicMock
) -> None:
    """Create the entry for the only water heater of the site."""
    result = await _submit_user(hass)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == DEVICE_NAME
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == f"site_{DEVICE_ID}"
    assert api.call_args.kwargs[CONF_USERNAME] == USER_INPUT[CONF_USERNAME]
    assert api.call_args.kwargs[CONF_PASSWORD] == USER_INPUT[CONF_PASSWORD]
    api.return_value.get_devices_info.assert_awaited_once_with("site")


@pytest.mark.parametrize(("error", "expected"), ERRORS)
async def test_user_error_shows_the_form_again(
    hass: HomeAssistant, api: MagicMock, error: type[Exception], expected: str
) -> None:
    """Report the failure, then create the entry once the login works."""
    api.return_value.authenticate.side_effect = error

    result = await _submit_user(hass)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": expected}

    api.return_value.authenticate.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    "devices",
    [
        {},
        {"devicesByType": {}},
        {"devicesByType": {"LOAD_DEVICE": []}},
        {"devicesByType": {"LOAD_DEVICE": [{"deviceInfo": {"name": "No ID"}}]}},
    ],
)
async def test_no_devices_shows_the_form_again(
    hass: HomeAssistant, api: MagicMock, devices: dict[str, Any]
) -> None:
    """Report a site without a water heater that has a device ID."""
    api.return_value.get_devices_info.return_value = devices

    result = await _submit_user(hass)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "no_devices"}


async def test_multiple_devices_ask_which_one(
    hass: HomeAssistant, api: MagicMock
) -> None:
    """Let the user pick a water heater and create the entry for it."""
    api.return_value.get_devices_info.return_value = _two_devices()

    result = await _submit_user(hass)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "select_device"
    schema = result["data_schema"]
    assert schema.schema[CONF_DEVICE_ID].container == {
        DEVICE_ID: DEVICE_NAME,
        SECOND_DEVICE_ID: SECOND_DEVICE_NAME,
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE_ID: SECOND_DEVICE_ID}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == SECOND_DEVICE_NAME
    assert result["data"] == {**ENTRY_DATA, CONF_DEVICE_ID: SECOND_DEVICE_ID}
    assert result["result"].unique_id == f"site_{SECOND_DEVICE_ID}"


@pytest.mark.usefixtures("api")
async def test_single_device_already_configured(hass: HomeAssistant) -> None:
    """Abort when the only water heater of the site is already set up."""
    add_config_entry(hass)

    result = await _submit_user(hass)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_selected_device_already_configured(
    hass: HomeAssistant, api: MagicMock
) -> None:
    """Abort when the selected water heater is already set up."""
    add_config_entry(hass)
    api.return_value.get_devices_info.return_value = _two_devices()
    result = await _submit_user(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE_ID: DEVICE_ID}
    )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_shows_the_password_form(hass: HomeAssistant) -> None:
    """Ask only for the password of the configured account."""
    result = await add_config_entry(hass).start_reauth_flow(hass)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert list(result["data_schema"].schema) == [CONF_PASSWORD]
    assert (
        result["description_placeholders"][CONF_USERNAME] == ENTRY_DATA[CONF_USERNAME]
    )


async def _confirm_reauth(hass: HomeAssistant, password: str) -> ConfigFlowResult:
    """Start reauth for the entry and submit the given password."""
    result = await hass.config_entries.async_entries(DOMAIN)[0].start_reauth_flow(hass)
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: password}
    )


async def test_reauth_uses_the_configured_username(
    hass: HomeAssistant, api: MagicMock
) -> None:
    """Verify the new password against the account stored in the entry."""
    add_config_entry(hass)

    await _confirm_reauth(hass, "new-password")

    assert api.call_args.kwargs[CONF_USERNAME] == ENTRY_DATA[CONF_USERNAME]
    assert api.call_args.kwargs[CONF_PASSWORD] == "new-password"


@pytest.mark.usefixtures("api")
async def test_reauth_saves_the_password_and_reloads(
    hass: HomeAssistant, setup_entry: AsyncMock
) -> None:
    """Store only the password and let Home Assistant reload the entry."""
    entry = add_config_entry(hass)

    result = await _confirm_reauth(hass, "new-password")
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {**ENTRY_DATA, CONF_PASSWORD: "new-password"}
    setup_entry.assert_awaited_once()


@pytest.mark.parametrize(("error", "expected"), ERRORS)
async def test_reauth_error_shows_the_form_again(
    hass: HomeAssistant,
    api: MagicMock,
    setup_entry: AsyncMock,
    error: type[Exception],
    expected: str,
) -> None:
    """Report the failure and save nothing."""
    entry = add_config_entry(hass)
    api.return_value.authenticate.side_effect = error

    result = await _confirm_reauth(hass, "new-password")
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": expected}
    assert entry.data == ENTRY_DATA
    setup_entry.assert_not_awaited()


async def _submit_reconfigure(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> ConfigFlowResult:
    """Start reconfiguring the entry and submit the given input."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await entry.start_reconfigure_flow(hass)
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


async def test_reconfigure_shows_the_prefilled_form(hass: HomeAssistant) -> None:
    """Prefill username and site ID, but not the password."""
    result = await add_config_entry(hass).start_reconfigure_flow(hass)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {}
    assert list(result["data_schema"].schema) == list(USER_INPUT)
    assert result["data_schema"]({}) == {
        CONF_USERNAME: ENTRY_DATA[CONF_USERNAME],
        CONF_SITE_ID: ENTRY_DATA[CONF_SITE_ID],
    }


async def test_reconfigure_saves_the_account_and_reloads(
    hass: HomeAssistant, api: MagicMock, setup_entry: AsyncMock
) -> None:
    """Verify the new account against the site, store it and reload."""
    entry = add_config_entry(hass)
    user_input = {
        **USER_INPUT,
        CONF_USERNAME: "new@example.com",
        CONF_PASSWORD: "new-password",
    }

    result = await _submit_reconfigure(hass, user_input)
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {**ENTRY_DATA, **user_input}
    assert entry.unique_id == f"site_{DEVICE_ID}"
    assert api.call_args.kwargs[CONF_USERNAME] == "new@example.com"
    assert api.call_args.kwargs[CONF_PASSWORD] == "new-password"
    api.return_value.get_devices_info.assert_awaited_once_with("site")
    setup_entry.assert_awaited_once()


async def test_reconfigure_without_password_keeps_the_stored_one(
    hass: HomeAssistant, api: MagicMock
) -> None:
    """Verify and keep the stored password when the field is left empty."""
    entry = add_config_entry(hass)
    user_input = {CONF_USERNAME: "new@example.com", CONF_SITE_ID: "site"}

    result = await _submit_reconfigure(hass, user_input)

    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {**ENTRY_DATA, CONF_USERNAME: "new@example.com"}
    assert api.call_args.kwargs[CONF_PASSWORD] == ENTRY_DATA[CONF_PASSWORD]


@pytest.mark.parametrize(("error", "expected"), ERRORS)
async def test_reconfigure_error_shows_the_form_again(
    hass: HomeAssistant,
    api: MagicMock,
    setup_entry: AsyncMock,
    error: type[Exception],
    expected: str,
) -> None:
    """Report the failure, keep the input and save nothing."""
    entry = add_config_entry(hass)
    api.return_value.authenticate.side_effect = error
    user_input = {**USER_INPUT, CONF_USERNAME: "new@example.com"}

    result = await _submit_reconfigure(hass, user_input)
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": expected}
    assert result["data_schema"]({})[CONF_USERNAME] == "new@example.com"
    assert entry.data == ENTRY_DATA
    setup_entry.assert_not_awaited()


async def test_reconfigure_site_without_devices_shows_the_form_again(
    hass: HomeAssistant, api: MagicMock
) -> None:
    """Report a site without any water heater, like the user flow does."""
    entry = add_config_entry(hass)
    api.return_value.get_devices_info.return_value = {}

    result = await _submit_reconfigure(hass, USER_INPUT)

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "no_devices"}
    assert entry.data == ENTRY_DATA


@pytest.mark.parametrize(
    ("site_id", "device_id"),
    [
        # The site holds another water heater only.
        ("site", SECOND_DEVICE_ID),
        # The site holds the water heater, but the unique ID would change.
        ("other-site", DEVICE_ID),
    ],
)
async def test_reconfigure_other_unique_id_aborts(
    hass: HomeAssistant,
    api: MagicMock,
    setup_entry: AsyncMock,
    site_id: str,
    device_id: str,
) -> None:
    """Refuse a site that would give the entry another unique ID."""
    entry = add_config_entry(hass)
    devices = load_fixture("info.json")
    devices["devicesByType"]["LOAD_DEVICE"][0]["deviceInfo"]["deviceId"] = device_id
    api.return_value.get_devices_info.return_value = devices

    result = await _submit_reconfigure(hass, {**USER_INPUT, CONF_SITE_ID: site_id})
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
    assert entry.data == ENTRY_DATA
    setup_entry.assert_not_awaited()
