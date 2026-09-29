"""Tests for the diagnostics download."""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from custom_components.solaredge_hotwater.api import ApiError
from custom_components.solaredge_hotwater.const import (
    CONF_DEVICE_ID,
    CONF_SCAN_INTERVAL,
    CONF_SITE_ID,
    DEVICE_STATE_PATH,
)
from custom_components.solaredge_hotwater.coordinator import (
    SolarEdgeWarmwaterCoordinator,
)
from custom_components.solaredge_hotwater.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .common import load_fixture, make_data

USERNAME = "jane.doe@example.com"
PASSWORD = "hunter2-secret"  # noqa: S105
SITE_ID = "4711815"
DEVICE_ID = "93428867"
SERIAL = "SN-7F3A99C2"
TOKEN = "eyJ-access-token-value"  # noqa: S105

SECRETS = [USERNAME, PASSWORD, SITE_ID, DEVICE_ID, SERIAL, TOKEN]


def _info() -> dict[str, Any]:
    """Return a recorded /info response with distinctive identifiers."""
    info = copy.deepcopy(load_fixture("info_with_schedule.json"))
    info["deviceInfo"]["deviceId"] = DEVICE_ID
    info["deviceInfo"]["serialNumber"] = SERIAL
    return info


def _state() -> dict[str, Any]:
    """Return a /state response that also carries identifiers and a token."""
    return {
        "activationMode": "AUTO",
        "percentageLevel": 100,
        "siteId": SITE_ID,
        "deviceId": DEVICE_ID,
        "token": TOKEN,
        "measurements": {"power": 1500},
    }


@pytest.fixture
def entry() -> MagicMock:
    """Return a config entry with credentials, identifiers and options."""
    entry = MagicMock()
    entry.title = "SolarEdge Heizstab"
    entry.data = {
        CONF_USERNAME: USERNAME,
        CONF_PASSWORD: PASSWORD,
        CONF_SITE_ID: SITE_ID,
        CONF_DEVICE_ID: DEVICE_ID,
    }
    entry.options = {CONF_SCAN_INTERVAL: 30}
    return entry


@pytest.fixture
def coordinator(entry: MagicMock) -> SolarEdgeWarmwaterCoordinator:
    """Return a coordinator after a failed update, attached to the entry."""
    coordinator = SolarEdgeWarmwaterCoordinator(MagicMock(), entry, MagicMock())
    coordinator.data = make_data(state=_state(), info=_info())
    path = DEVICE_STATE_PATH.format(site_id=SITE_ID, device_id=DEVICE_ID)
    coordinator.last_exception = ApiError(f"API request failed: GET {path} -> 500")
    coordinator.last_update_success = False
    entry.runtime_data = coordinator
    return coordinator


def _diagnostics(entry: MagicMock) -> dict[str, Any]:
    """Return the diagnostics for the entry."""
    return asyncio.run(async_get_config_entry_diagnostics(MagicMock(), entry))


@pytest.mark.usefixtures("coordinator")
def test_diagnostics_contain_responses_options_and_status(entry: MagicMock) -> None:
    """The raw responses, the options and the coordinator status are included."""
    result = _diagnostics(entry)

    assert result["entry"]["options"] == {CONF_SCAN_INTERVAL: 30}
    assert result["state"]["measurements"] == {"power": 1500}
    assert result["info"]["deviceInfo"]["model"] == "SMRT-HOT-WTR-30-S2"
    assert result["info"]["schedules"] == _info()["schedules"]
    status = result["coordinator"]
    assert "API request failed" in status.pop("last_exception")
    assert status == {
        "last_update_success": False,
        "failed_state_updates": 0,
        "update_interval": 30.0,
        "last_info_update": "2026-09-21T00:00:00+00:00",
    }


@pytest.mark.usefixtures("coordinator")
def test_diagnostics_redact_credentials_and_identifiers(entry: MagicMock) -> None:
    """No credential, identifier or token appears in plain text."""
    dump = json.dumps(_diagnostics(entry))

    for secret in SECRETS:
        assert secret not in dump
    assert "**REDACTED**" in dump


def test_diagnostics_before_first_update(
    entry: MagicMock, coordinator: SolarEdgeWarmwaterCoordinator
) -> None:
    """Without data yet, the responses are empty instead of failing."""
    coordinator.data = None

    result = _diagnostics(entry)

    assert result["state"] is None
    assert result["info"] is None
    assert result["coordinator"]["last_info_update"] is None
    for secret in SECRETS:
        assert secret not in json.dumps(result)
