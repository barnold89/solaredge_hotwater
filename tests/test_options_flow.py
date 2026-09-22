"""Tests for the options flow and the confirmation of short intervals."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solaredge_hotwater.config_flow import (
    SolarEdgeWarmwaterOptionsFlow,
)
from custom_components.solaredge_hotwater.const import CONF_SCAN_INTERVAL

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult


def _flow(options: dict[str, Any]) -> SolarEdgeWarmwaterOptionsFlow:
    """Create an options flow for an entry with the given saved options."""
    entry = MagicMock()
    entry.options = options
    return SolarEdgeWarmwaterOptionsFlow(entry)


def _submit(
    flow: SolarEdgeWarmwaterOptionsFlow, scan_interval: int
) -> ConfigFlowResult:
    """Submit the options form with the given polling interval."""
    return asyncio.run(flow.async_step_init({CONF_SCAN_INTERVAL: scan_interval}))


@pytest.mark.parametrize(("options", "saved"), [({}, 60), ({CONF_SCAN_INTERVAL: 5}, 5)])
def test_form_shows_saved_interval(options: dict[str, Any], saved: int) -> None:
    """Prefill the saved interval, 60 s without options, and allow 1 to 3600 s."""
    result = asyncio.run(_flow(options).async_step_init())

    assert result["type"] == FlowResultType.FORM
    schema = result["data_schema"]
    assert schema({}) == {CONF_SCAN_INTERVAL: saved}
    assert schema({CONF_SCAN_INTERVAL: 1}) == {CONF_SCAN_INTERVAL: 1}
    with pytest.raises(vol.Invalid):
        schema({CONF_SCAN_INTERVAL: 0})
    with pytest.raises(vol.Invalid):
        schema({CONF_SCAN_INTERVAL: 3601})


@pytest.mark.parametrize(
    ("options", "scan_interval"),
    [({}, 5), ({CONF_SCAN_INTERVAL: 60}, 9), ({CONF_SCAN_INTERVAL: 10}, 1)],
)
def test_short_interval_asks_for_confirmation(
    options: dict[str, Any], scan_interval: int
) -> None:
    """Warn before switching below 10 s and save nothing yet."""
    result = _submit(_flow(options), scan_interval)

    assert result["type"] == FlowResultType.MENU
    assert result["step_id"] == "confirm_interval"
    assert result["menu_options"] == ["save_interval", "change_interval"]
    assert result["description_placeholders"] == {"scan_interval": str(scan_interval)}


@pytest.mark.parametrize(
    ("options", "scan_interval"),
    [
        ({}, 10),
        ({CONF_SCAN_INTERVAL: 60}, 29),
        ({}, 3600),
        ({CONF_SCAN_INTERVAL: 5}, 5),
        ({CONF_SCAN_INTERVAL: 5}, 2),
        ({CONF_SCAN_INTERVAL: 5}, 60),
    ],
)
def test_interval_saved_without_confirmation(
    options: dict[str, Any], scan_interval: int
) -> None:
    """Save 10 s and more directly, and short intervals that were already short."""
    result = _submit(_flow(options), scan_interval)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_SCAN_INTERVAL: scan_interval}


def test_confirmed_short_interval_is_saved() -> None:
    """Save the short interval once the warning is confirmed."""
    flow = _flow({})
    _submit(flow, 5)

    result = asyncio.run(flow.async_step_save_interval())

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_SCAN_INTERVAL: 5}


def test_change_interval_returns_to_form_with_10_s() -> None:
    """Return to the form prefilled with 10 s and ask again for a short interval."""
    flow = _flow({})
    _submit(flow, 5)

    result = asyncio.run(flow.async_step_change_interval())

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["data_schema"]({}) == {CONF_SCAN_INTERVAL: 10}
    assert _submit(flow, 5)["type"] == FlowResultType.MENU
