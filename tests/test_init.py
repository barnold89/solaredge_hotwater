"""Tests for how setup maps API failures to config entry states."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from custom_components.solaredge_hotwater import async_setup_entry
from custom_components.solaredge_hotwater.api import (
    ApiError,
    AuthenticationError,
    LoginUnavailableError,
)


def _setup(error: Exception) -> None:
    """Run setup against an API client whose login raises that error."""
    entry = MagicMock()
    entry.data = {CONF_USERNAME: "user", CONF_PASSWORD: "password"}
    with (
        patch("custom_components.solaredge_hotwater.async_get_clientsession"),
        patch("custom_components.solaredge_hotwater.SolarEdgeWarmwaterAPI") as client,
    ):
        client.return_value.authenticate = AsyncMock(side_effect=error)
        asyncio.run(async_setup_entry(MagicMock(), entry))


@pytest.mark.parametrize(
    "error", [LoginUnavailableError("login page returned 503"), ApiError("HTTP 500")]
)
def test_unavailable_login_retries_setup(error: Exception) -> None:
    """A broken login lets Home Assistant retry instead of asking for credentials."""
    with pytest.raises(ConfigEntryNotReady):
        _setup(error)


def test_rejected_credentials_ask_for_reauth() -> None:
    """Only rejected credentials send the user to the reauth dialog."""
    with pytest.raises(ConfigEntryAuthFailed):
        _setup(AuthenticationError("Credentials rejected by SolarEdge"))
