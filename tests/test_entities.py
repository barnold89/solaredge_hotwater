"""Tests for the entities reading from HotWaterData."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.solaredge_hotwater.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    SolarEdgeWarmwaterBinarySensor,
)
from custom_components.solaredge_hotwater.select import SolarEdgeOperationMode
from custom_components.solaredge_hotwater.sensor import (
    SENSOR_DESCRIPTIONS,
    SolarEdgeWarmwaterSensor,
)

from .common import load_fixture, make_data


def _coordinator() -> MagicMock:
    """Return a mocked coordinator with the recorded /state and /info responses."""
    coordinator = MagicMock()
    coordinator.data = make_data(
        state=load_fixture("state.json"), info=load_fixture("info_with_schedule.json")
    )
    coordinator.site_id = "site"
    coordinator.device_id = "device"
    return coordinator


def test_unique_ids_unchanged() -> None:
    """Keep the unique IDs so history and automations survive the update."""
    coordinator = _coordinator()
    entities = [
        *(SolarEdgeWarmwaterSensor(coordinator, d) for d in SENSOR_DESCRIPTIONS),
        *(
            SolarEdgeWarmwaterBinarySensor(coordinator, d)
            for d in BINARY_SENSOR_DESCRIPTIONS
        ),
        SolarEdgeOperationMode(coordinator),
    ]

    assert sorted(entity.unique_id for entity in entities) == [
        "site_device_active_power",
        "site_device_auto_off_reason",
        "site_device_communication_status",
        "site_device_device_status",
        "site_device_excess_pv_enabled",
        "site_device_operation_mode",
        "site_device_power_level",
        "site_device_rated_power",
        "site_device_schedule_type",
        "site_device_temperature",
    ]


def test_sensor_values() -> None:
    """Read sensor values from /state and /info."""
    coordinator = _coordinator()
    values = {
        d.key: SolarEdgeWarmwaterSensor(coordinator, d).native_value
        for d in SENSOR_DESCRIPTIONS
    }

    assert values == {
        "temperature": 67.60212,
        "device_status": "ACTIVE",
        "auto_off_reason": "PENDING_EXCESS_SOLAR",
        "schedule_type": "EXCESS_PV",
        "rated_power": 3000,
        # The recorded idle state carries no activePowerMeter at all.
        "active_power": 0,
        "power_level": 0,
    }


def test_binary_sensor_values() -> None:
    """Read binary sensor values from /state and /info."""
    coordinator = _coordinator()
    values = {
        d.key: SolarEdgeWarmwaterBinarySensor(coordinator, d).is_on
        for d in BINARY_SENSOR_DESCRIPTIONS
    }

    assert values == {"communication_status": True, "excess_pv_enabled": True}


def test_device_info() -> None:
    """Build the device info from deviceInfo in /info."""
    device_info = SolarEdgeOperationMode(_coordinator()).device_info

    assert device_info["name"] == "SolarEdge Heizstab"
    assert device_info["model"] == "SMRT-HOT-WTR-30-S2"
    assert device_info["serial_number"] == "0000000"
    assert device_info["configuration_url"] == (
        "https://monitoring.solaredge.com/one#/residential/dashboard?siteId=site"
    )


def _active_power(state: dict[str, Any]) -> Any:
    """Return the active power sensor value for a /state response."""
    coordinator = _coordinator()
    coordinator.data = make_data(state=state)
    description = next(d for d in SENSOR_DESCRIPTIONS if d.key == "active_power")
    return SolarEdgeWarmwaterSensor(coordinator, description).native_value


def test_active_power_idle() -> None:
    """Report 0 W for the recorded idle state without activePowerMeter."""
    assert _active_power(load_fixture("state.json")) == 0


def test_active_power_value() -> None:
    """Report activePowerMeter while the heating element draws power."""
    state = load_fixture("state.json")
    state["measurements"]["activePowerMeter"] = 2100.5

    assert _active_power(state) == 2100.5


@pytest.mark.parametrize("status", ["INACTIVE", None])
def test_active_power_no_connection(status: str | None) -> None:
    """Report unknown when the cloud has no connection to the device."""
    state = load_fixture("state.json")
    # None stands for a response without portiaCommunicationStatus.
    state.pop("portiaCommunicationStatus")
    if status is not None:
        state["portiaCommunicationStatus"] = status

    assert _active_power(state) is None
