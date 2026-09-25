"""Tests for API fields that are explicitly null."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solaredge_hotwater.const import CONF_DEVICE_ID, CONF_SITE_ID
from custom_components.solaredge_hotwater.coordinator import (
    HotWaterData,
    SolarEdgeWarmwaterCoordinator,
)
from custom_components.solaredge_hotwater.sensor import (
    SENSOR_DESCRIPTIONS,
    SolarEdgeWarmwaterSensor,
)

from .common import make_data


def _sensor(key: str, data: HotWaterData) -> SolarEdgeWarmwaterSensor:
    """Create a sensor entity backed by a mocked coordinator."""
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.site_id = "site"
    coordinator.device_id = "device"
    description = next(d for d in SENSOR_DESCRIPTIONS if d.key == key)
    return SolarEdgeWarmwaterSensor(coordinator, description)


def _update(info: dict[str, Any] | None) -> HotWaterData:
    """Run one coordinator update with the given /info response."""
    api = MagicMock()
    api.get_device_info = AsyncMock(return_value=info)
    api.get_device_state = AsyncMock(return_value={"activationMode": "AUTO"})
    entry = MagicMock()
    entry.data = {CONF_SITE_ID: "site", CONF_DEVICE_ID: "dev"}
    entry.options = {}
    coordinator = SolarEdgeWarmwaterCoordinator(MagicMock(), entry, api)

    return asyncio.run(coordinator._async_update_data())


def test_sensor_measurements_null() -> None:
    """Return None instead of raising when measurements is null."""
    data = make_data(state={"measurements": None})
    assert _sensor("temperature", data).native_value is None


def test_device_info_null() -> None:
    """Fall back to defaults when deviceInfo is null."""
    sensor = _sensor("temperature", make_data(info={"deviceInfo": None}))

    device_info = sensor.device_info

    assert device_info["name"] == "SolarEdge Warmwater"
    assert device_info["manufacturer"] == "SolarEdge"


def test_device_configurations_null() -> None:
    """Return the state and no rated power when deviceConfigurations is null."""
    data = _update({"deviceConfigurations": None})

    assert data.state["activationMode"] == "AUTO"
    assert data.configurations == {}
    assert _sensor("rated_power", data).native_value is None


@pytest.mark.parametrize(
    "info",
    [
        None,
        {},
        {"schedules": None},
        {"schedules": {}},
        {"schedules": {"allSchedules": None}},
    ],
)
def test_schedules_null(info: dict[str, Any] | None) -> None:
    """Return no schedules when /info or its schedule fields are null."""
    assert _update(info).schedules == []
