"""Water heater platform for SolarEdge Warmwater integration."""

from __future__ import annotations

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SolarEdgeWarmwaterConfigEntry
from .const import MODE_AUTO, MODE_OFF, MODE_ON, OPERATION_MODES
from .coordinator import SolarEdgeWarmwaterCoordinator
from .entity import SolarEdgeWarmwaterEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarEdgeWarmwaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the water heater platform."""
    coordinator = entry.runtime_data
    async_add_entities([SolarEdgeWaterHeater(coordinator)])


class SolarEdgeWaterHeater(SolarEdgeWarmwaterEntity, WaterHeaterEntity):
    """SolarEdge hot water heater entity."""

    _attr_supported_features = (
        WaterHeaterEntityFeature.OPERATION_MODE | WaterHeaterEntityFeature.ON_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_operation_list = OPERATION_MODES
    _attr_translation_key = "heater"

    def __init__(self, coordinator: SolarEdgeWarmwaterCoordinator) -> None:
        """Initialize the water heater."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.site_id}_{coordinator.device_id}_heater"

    @property
    def current_temperature(self) -> float | None:
        """Return the current water temperature."""
        measurements = self.coordinator.data.get("measurements", {})
        return measurements.get("measuredTemperature")

    @property
    def current_operation(self) -> str:
        """Return the current operation mode."""
        mode = self.coordinator.data.get("activationMode", "")
        level = self.coordinator.data.get("percentageLevel", 0)
        if mode == "AUTO":
            return MODE_AUTO
        if mode == "MANUAL" and level > 0:
            return MODE_ON
        return MODE_OFF

    @property
    def is_on(self) -> bool:
        """Return True if the heater is on."""
        return self.current_operation != MODE_OFF

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set the operation mode."""
        if operation_mode == MODE_AUTO:
            await self.coordinator.api.set_activation_state(
                self.coordinator.site_id,
                self.coordinator.device_id,
                "AUTO",
            )
        elif operation_mode == MODE_ON:
            # Use the current power level, or default to 100%
            level = self.coordinator.data.get("percentageLevel", 100) or 100
            await self.coordinator.api.set_activation_state(
                self.coordinator.site_id,
                self.coordinator.device_id,
                "MANUAL",
                level=level,
            )
        elif operation_mode == MODE_OFF:
            await self.coordinator.api.set_activation_state(
                self.coordinator.site_id,
                self.coordinator.device_id,
                "MANUAL",
                level=0,
            )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the heater on."""
        await self.async_set_operation_mode(MODE_ON)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the heater off."""
        await self.async_set_operation_mode(MODE_OFF)
