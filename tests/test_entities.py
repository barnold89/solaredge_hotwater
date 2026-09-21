"""Tests for the entities reading from HotWaterData."""

from __future__ import annotations

from unittest.mock import MagicMock

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

STATE = {
    "activationMode": "AUTO",
    "percentageLevel": 100,
    "deviceStatus": "ACTIVE",
    "scheduleType": "EXCESS_PV",
    "portiaCommunicationStatus": "ACTIVE",
    "measurements": {"measuredTemperature": 70.0, "activePowerMeter": 0},
}


def _coordinator() -> MagicMock:
    """Return a mocked coordinator with the recorded /info response."""
    coordinator = MagicMock()
    coordinator.data = make_data(
        state=STATE, info=load_fixture("info_with_schedule.json")
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
        "temperature": 70.0,
        "device_status": "ACTIVE",
        "auto_off_reason": None,
        "schedule_type": "EXCESS_PV",
        "rated_power": 3000,
        "active_power": 0,
        "power_level": 100,
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
