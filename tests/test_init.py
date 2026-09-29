"""Tests for setting up and unloading a config entry."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState

from custom_components.solaredge_hotwater.api import (
    ApiError,
    AuthenticationError,
    LoginUnavailableError,
)
from custom_components.solaredge_hotwater.const import DOMAIN

from .common import DEVICE_ID, add_config_entry, load_fixture

if TYPE_CHECKING:
    from collections.abc import Iterator

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import entity_registry as er


@pytest.fixture
def api() -> Iterator[MagicMock]:
    """Patch the API client to answer with the recorded /state and /info."""
    with patch("custom_components.solaredge_hotwater.SolarEdgeWarmwaterAPI") as client:
        client.return_value.authenticate = AsyncMock(return_value=True)
        client.return_value.get_device_state = AsyncMock(
            return_value=load_fixture("state.json")
        )
        client.return_value.get_device_info = AsyncMock(
            return_value=load_fixture("info_with_schedule.json")
        )
        yield client


async def test_setup_creates_entities_and_unload_removes_them(
    hass: HomeAssistant, entity_registry: er.EntityRegistry, api: MagicMock
) -> None:
    """Set up the entry from the recorded responses and unload it again."""
    entry = add_config_entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    api.return_value.get_device_state.assert_awaited_once_with("site", DEVICE_ID)
    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"site_{DEVICE_ID}_temperature"
    )
    assert entity_id is not None
    assert hass.states.get(entity_id).state == "70.0"
    mode_id = entity_registry.async_get_entity_id(
        "select", DOMAIN, f"site_{DEVICE_ID}_operation_mode"
    )
    assert hass.states.get(mode_id).state == "auto"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize(
    "error", [LoginUnavailableError("login page returned 503"), ApiError("HTTP 500")]
)
async def test_unavailable_login_retries_setup(
    hass: HomeAssistant, api: MagicMock, error: Exception
) -> None:
    """A broken login lets Home Assistant retry instead of asking for credentials."""
    api.return_value.authenticate.side_effect = error
    entry = add_config_entry(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.config_entries.flow.async_progress()


async def test_rejected_credentials_ask_for_reauth(
    hass: HomeAssistant, api: MagicMock
) -> None:
    """Only rejected credentials send the user to the reauth dialog."""
    api.return_value.authenticate.side_effect = AuthenticationError(
        "Credentials rejected by SolarEdge"
    )
    entry = add_config_entry(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
    assert flows[0]["context"]["entry_id"] == entry.entry_id
