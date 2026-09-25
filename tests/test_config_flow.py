"""Tests for the re-authentication flow."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solaredge_hotwater.api import AuthenticationError
from custom_components.solaredge_hotwater.config_flow import (
    SolarEdgeWarmwaterConfigFlow,
)
from custom_components.solaredge_hotwater.const import (
    CONF_DEVICE_ID,
    CONF_SITE_ID,
    DOMAIN,
)

from .common import ENTRY_ID, mock_hass

if TYPE_CHECKING:
    from collections.abc import Iterator

    from homeassistant.config_entries import ConfigFlowResult

ENTRY_DATA = {
    CONF_USERNAME: "user@example.com",
    CONF_PASSWORD: "old-password",
    CONF_SITE_ID: "site",
    CONF_DEVICE_ID: "device",
}


@pytest.fixture
def entry() -> MagicMock:
    """Return the config entry that is being re-authenticated."""
    entry = MagicMock()
    entry.data = dict(ENTRY_DATA)
    entry.entry_id = ENTRY_ID
    return entry


@pytest.fixture
def flow(entry: MagicMock) -> SolarEdgeWarmwaterConfigFlow:
    """Return a config flow in a reauth context for that entry."""
    flow = SolarEdgeWarmwaterConfigFlow()
    flow.hass = mock_hass(entry)
    flow.handler = DOMAIN
    flow.context = {"source": SOURCE_REAUTH, "entry_id": ENTRY_ID}
    return flow


@pytest.fixture
def api() -> Iterator[MagicMock]:
    """Patch the API client and the session it is handed, and return the client."""
    with (
        patch(
            "custom_components.solaredge_hotwater.config_flow.async_get_clientsession"
        ),
        patch(
            "custom_components.solaredge_hotwater.config_flow.SolarEdgeWarmwaterAPI"
        ) as client,
    ):
        client.return_value.authenticate = AsyncMock(return_value=True)
        yield client


def _confirm(flow: SolarEdgeWarmwaterConfigFlow, password: str) -> ConfigFlowResult:
    """Submit the reauth form with the given password."""
    return asyncio.run(flow.async_step_reauth_confirm({CONF_PASSWORD: password}))


def test_reauth_shows_the_password_form(flow: SolarEdgeWarmwaterConfigFlow) -> None:
    """Start reauth the way Home Assistant does, with the entry data."""
    result = asyncio.run(flow.async_step_reauth(ENTRY_DATA))

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    schema = result["data_schema"]
    assert list(schema.schema) == [CONF_PASSWORD]
    assert (
        result["description_placeholders"][CONF_USERNAME] == ENTRY_DATA[CONF_USERNAME]
    )


def test_reauth_uses_the_configured_username(
    flow: SolarEdgeWarmwaterConfigFlow, api: MagicMock
) -> None:
    """Verify the new password against the account stored in the entry."""
    _confirm(flow, "new-password")

    assert api.call_args.kwargs[CONF_USERNAME] == ENTRY_DATA[CONF_USERNAME]
    assert api.call_args.kwargs[CONF_PASSWORD] == "new-password"


@pytest.mark.usefixtures("api")
def test_reauth_saves_the_password_and_reloads(
    flow: SolarEdgeWarmwaterConfigFlow, entry: MagicMock
) -> None:
    """Store only the password and let Home Assistant reload the entry."""
    result = _confirm(flow, "new-password")

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    config_entries = flow.hass.config_entries
    assert config_entries.async_update_entry.call_args.kwargs["data"] == {
        **ENTRY_DATA,
        CONF_PASSWORD: "new-password",
    }
    config_entries.async_schedule_reload.assert_called_once_with(entry.entry_id)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (AuthenticationError, "invalid_auth"),
        (aiohttp.ClientError, "cannot_connect"),
        (TimeoutError, "cannot_connect"),
        (RuntimeError, "unknown"),
    ],
)
def test_reauth_error_shows_the_form_again(
    flow: SolarEdgeWarmwaterConfigFlow,
    api: MagicMock,
    error: type[Exception],
    expected: str,
) -> None:
    """Report the failure and save nothing."""
    api.return_value.authenticate = AsyncMock(side_effect=error)

    result = _confirm(flow, "new-password")

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": expected}
    flow.hass.config_entries.async_update_entry.assert_not_called()
