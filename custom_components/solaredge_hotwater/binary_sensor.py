"""Binary sensor platform for SolarEdge Warmwater integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SolarEdgeWarmwaterConfigEntry
from .coordinator import SolarEdgeWarmwaterCoordinator
from .entity import SolarEdgeWarmwaterEntity


@dataclass(frozen=True, kw_only=True)
class SolarEdgeBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a SolarEdge Warmwater binary sensor."""

    value_fn: str
    on_value: str


BINARY_SENSOR_DESCRIPTIONS: tuple[SolarEdgeBinarySensorDescription, ...] = (
    SolarEdgeBinarySensorDescription(
        key="communication_status",
        translation_key="communication_status",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn="portiaCommunicationStatus",
        on_value="ACTIVE",
    ),
    SolarEdgeBinarySensorDescription(
        key="excess_pv_enabled",
        translation_key="excess_pv_enabled",
        icon="mdi:solar-power-variant",
        value_fn="excessPVEnabled",
        on_value="ON",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarEdgeWarmwaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator = entry.runtime_data
    async_add_entities(
        SolarEdgeWarmwaterBinarySensor(coordinator, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
    )


class SolarEdgeWarmwaterBinarySensor(SolarEdgeWarmwaterEntity, BinarySensorEntity):
    """SolarEdge Warmwater binary sensor entity."""

    entity_description: SolarEdgeBinarySensorDescription

    def __init__(
        self,
        coordinator: SolarEdgeWarmwaterCoordinator,
        description: SolarEdgeBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.site_id}_{coordinator.device_id}_{description.key}"
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if the binary sensor is on."""
        value = self.coordinator.data.get(self.entity_description.value_fn)
        if value is None:
            return None
        return value == self.entity_description.on_value
