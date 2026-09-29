"""Tests for the options flow and the confirmation of short intervals."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solaredge_hotwater.const import CONF_SCAN_INTERVAL

from .common import add_config_entry

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant


async def _init(hass: HomeAssistant, options: dict[str, Any]) -> ConfigFlowResult:
    """Open the options of an entry with the given saved options."""
    entry = add_config_entry(hass, options)
    return await hass.config_entries.options.async_init(entry.entry_id)


async def _submit(
    hass: HomeAssistant, result: ConfigFlowResult, scan_interval: int
) -> ConfigFlowResult:
    """Submit the options form with the given polling interval."""
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: scan_interval}
    )


async def _choose(
    hass: HomeAssistant, result: ConfigFlowResult, step_id: str
) -> ConfigFlowResult:
    """Pick an option from the confirmation menu."""
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step_id}
    )


@pytest.mark.parametrize(("options", "saved"), [({}, 60), ({CONF_SCAN_INTERVAL: 5}, 5)])
async def test_form_shows_saved_interval(
    hass: HomeAssistant, options: dict[str, Any], saved: int
) -> None:
    """Prefill the saved interval, 60 s without options, and allow 1 to 3600 s."""
    result = await _init(hass, options)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
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
async def test_short_interval_asks_for_confirmation(
    hass: HomeAssistant, options: dict[str, Any], scan_interval: int
) -> None:
    """Warn before switching below 10 s and save nothing yet."""
    result = await _submit(hass, await _init(hass, options), scan_interval)

    assert result["type"] == FlowResultType.MENU
    assert result["step_id"] == "confirm_interval"
    assert result["menu_options"] == ["save_interval", "change_interval"]
    assert result["description_placeholders"] == {"scan_interval": str(scan_interval)}
    assert hass.config_entries.async_entries()[0].options == options


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
async def test_interval_saved_without_confirmation(
    hass: HomeAssistant, options: dict[str, Any], scan_interval: int
) -> None:
    """Save 10 s and more directly, and short intervals that were already short."""
    result = await _submit(hass, await _init(hass, options), scan_interval)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_SCAN_INTERVAL: scan_interval}
    assert hass.config_entries.async_entries()[0].options == {
        CONF_SCAN_INTERVAL: scan_interval
    }


async def test_confirmed_short_interval_is_saved(hass: HomeAssistant) -> None:
    """Save the short interval once the warning is confirmed."""
    result = await _submit(hass, await _init(hass, {}), 5)

    result = await _choose(hass, result, "save_interval")

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_SCAN_INTERVAL: 5}
    assert hass.config_entries.async_entries()[0].options == {CONF_SCAN_INTERVAL: 5}


@pytest.mark.parametrize(
    ("options", "saved"), [({}, 60), ({CONF_SCAN_INTERVAL: 30}, 30)]
)
async def test_change_interval_returns_to_form_with_saved_interval(
    hass: HomeAssistant, options: dict[str, Any], saved: int
) -> None:
    """Return to the form with the saved interval, 60 s without options."""
    result = await _submit(hass, await _init(hass, options), 5)

    result = await _choose(hass, result, "change_interval")

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["data_schema"]({}) == {CONF_SCAN_INTERVAL: saved}
    assert (await _submit(hass, result, 5))["type"] == FlowResultType.MENU
