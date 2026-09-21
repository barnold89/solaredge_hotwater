"""Sensor platform for SolarEdge Warmwater integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfPower,
    UnitOfTemperature,
)

from .entity import SolarEdgeWarmwaterEntity

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import SolarEdgeWarmwaterConfigEntry
    from .coordinator import HotWaterData, SolarEdgeWarmwaterCoordinator


@dataclass(frozen=True, kw_only=True)
class SolarEdgeSensorDescription(SensorEntityDescription):
    """Describe a SolarEdge Warmwater sensor."""

    value_fn: Callable[[HotWaterData], Any]


SENSOR_DESCRIPTIONS: tuple[SolarEdgeSensorDescription, ...] = (
    SolarEdgeSensorDescription(
        key="temperature",
        translation_key="temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.measurements.get("measuredTemperature"),
    ),
    SolarEdgeSensorDescription(
        key="device_status",
        translation_key="device_status",
        icon="mdi:information-outline",
        value_fn=lambda data: data.state.get("deviceStatus"),
    ),
    SolarEdgeSensorDescription(
        key="auto_off_reason",
        translation_key="auto_off_reason",
        icon="mdi:power-plug-off",
        value_fn=lambda data: data.state.get("autoOffReason"),
    ),
    SolarEdgeSensorDescription(
        key="schedule_type",
        translation_key="schedule_type",
        icon="mdi:calendar-clock",
        value_fn=lambda data: data.state.get("scheduleType"),
    ),
    SolarEdgeSensorDescription(
        key="rated_power",
        translation_key="rated_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.configurations.get("ratedPower"),
    ),
    SolarEdgeSensorDescription(
        key="active_power",
        translation_key="active_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data.measurements.get("activePowerMeter"),
    ),
    SolarEdgeSensorDescription(
        key="power_level",
        translation_key="power_level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:flash",
        value_fn=lambda data: data.state.get("percentageLevel"),
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: SolarEdgeWarmwaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator = entry.runtime_data
    async_add_entities(
        SolarEdgeWarmwaterSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    )


class SolarEdgeWarmwaterSensor(SolarEdgeWarmwaterEntity, SensorEntity):
    """SolarEdge Warmwater sensor entity."""

    entity_description: SolarEdgeSensorDescription

    def __init__(
        self,
        coordinator: SolarEdgeWarmwaterCoordinator,
        description: SolarEdgeSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.site_id}_{coordinator.device_id}_{description.key}"
        )

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)
