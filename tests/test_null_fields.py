"""Tests for API fields that are explicitly null."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.solaredge_hotwater.coordinator import (
    SolarEdgeWarmwaterCoordinator,
)
from custom_components.solaredge_hotwater.sensor import (
    SENSOR_DESCRIPTIONS,
    SolarEdgeWarmwaterSensor,
)


def _sensor(key: str, data: dict) -> SolarEdgeWarmwaterSensor:
    """Create a sensor entity backed by a mocked coordinator."""
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.site_id = "site"
    coordinator.device_id = "device"
    coordinator.device_info_data = None
    description = next(d for d in SENSOR_DESCRIPTIONS if d.key == key)
    return SolarEdgeWarmwaterSensor(coordinator, description)


def test_sensor_measurements_null() -> None:
    """Return None instead of raising when measurements is null."""
    assert _sensor("temperature", {"measurements": None}).native_value is None


def test_device_info_null() -> None:
    """Fall back to defaults when deviceInfo is null."""
    sensor = _sensor("temperature", {})
    sensor.coordinator.device_info_data = {"deviceInfo": None}

    device_info = sensor.device_info

    assert device_info["name"] == "SolarEdge Warmwater"
    assert device_info["manufacturer"] == "SolarEdge"


def test_coordinator_device_configurations_null() -> None:
    """Return the state when deviceConfigurations is null."""
    api = MagicMock()
    api.get_device_info = AsyncMock(return_value={"deviceConfigurations": None})
    api.get_device_state = AsyncMock(return_value={"activationMode": "AUTO"})
    # The coordinator does not pass config_entry yet (SE-05).
    with patch("homeassistant.helpers.frame.report_usage"):
        coordinator = SolarEdgeWarmwaterCoordinator(MagicMock(), api, "site", "dev")

    state = asyncio.run(coordinator._async_update_data())

    assert state["activationMode"] == "AUTO"
    assert state["ratedPower"] is None
