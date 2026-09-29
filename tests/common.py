"""Shared helpers for the tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solaredge_hotwater.const import (
    CONF_DEVICE_ID,
    CONF_SITE_ID,
    DOMAIN,
)
from custom_components.solaredge_hotwater.coordinator import HotWaterData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

FIXTURES = Path(__file__).parent / "fixtures"

# The device in the recorded responses, see tests/fixtures/info.json.
DEVICE_ID = "000000"
DEVICE_NAME = "SolarEdge Heizstab"

ENTRY_DATA = {
    CONF_USERNAME: "user@example.com",
    CONF_PASSWORD: "password",
    CONF_SITE_ID: "site",
    CONF_DEVICE_ID: DEVICE_ID,
}


def load_fixture(name: str) -> dict[str, Any]:
    """Load a recorded API response from tests/fixtures."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_data(
    state: dict[str, Any] | None = None, info: dict[str, Any] | None = None
) -> HotWaterData:
    """Build coordinator data from /state and /info responses."""
    return HotWaterData(
        state=state or {},
        info=info or {},
        schedules=[],
        last_info_update=datetime(2026, 9, 21, tzinfo=UTC),
    )


def add_config_entry(
    hass: HomeAssistant, options: dict[str, Any] | None = None
) -> MockConfigEntry:
    """Add a config entry for the recorded device to hass and return it."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=DEVICE_NAME,
        unique_id=f"{ENTRY_DATA[CONF_SITE_ID]}_{DEVICE_ID}",
        data=ENTRY_DATA,
        options=options or {},
    )
    entry.add_to_hass(hass)
    return entry
