"""Number platform for SolarEdge Warmwater integration."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SolarEdgeWarmwaterConfigEntry
from .coordinator import SolarEdgeWarmwaterCoordinator
from .entity import SolarEdgeWarmwaterEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarEdgeWarmwaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number platform."""
    coordinator = entry.runtime_data
    async_add_entities([SolarEdgePowerLevel(coordinator)])


class SolarEdgePowerLevel(SolarEdgeWarmwaterEntity, NumberEntity):
    """Number entity for controlling the heater power level."""

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_translation_key = "power_level"
    _attr_icon = "mdi:flash-circle"

    def __init__(self, coordinator: SolarEdgeWarmwaterCoordinator) -> None:
        """Initialize the power level entity."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.site_id}_{coordinator.device_id}_power_level"
        )

    @property
    def native_value(self) -> float | None:
        """Return the current power level."""
        return self.coordinator.data.get("percentageLevel")

    async def async_set_native_value(self, value: float) -> None:
        """Set the power level (implicitly switches to MANUAL mode)."""
        level = int(value)
        await self.coordinator.api.set_activation_state(
            self.coordinator.site_id,
            self.coordinator.device_id,
            "MANUAL",
            level=level,
        )
        await self.coordinator.async_request_refresh()
