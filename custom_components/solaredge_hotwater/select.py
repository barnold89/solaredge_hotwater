"""Select platform for SolarEdge Warmwater integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
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
    """Set up the select platform."""
    coordinator = entry.runtime_data
    async_add_entities([SolarEdgeOperationMode(coordinator)])


class SolarEdgeOperationMode(SolarEdgeWarmwaterEntity, SelectEntity):
    """Select entity for controlling the heater operation mode."""

    _attr_options = OPERATION_MODES
    _attr_translation_key = "operation_mode"
    _attr_icon = "mdi:water-boiler"

    def __init__(self, coordinator: SolarEdgeWarmwaterCoordinator) -> None:
        """Initialize the operation mode entity."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.site_id}_{coordinator.device_id}_operation_mode"
        )

    @property
    def current_option(self) -> str | None:
        """Return the current operation mode."""
        mode = self.coordinator.data.get("activationMode", "")
        level = self.coordinator.data.get("percentageLevel", 0)
        if mode == "AUTO":
            return MODE_AUTO
        if mode == "MANUAL" and level > 0:
            return MODE_ON
        return MODE_OFF

    async def async_select_option(self, option: str) -> None:
        """Set the operation mode."""
        if option == MODE_AUTO:
            await self.coordinator.api.set_activation_state(
                self.coordinator.site_id,
                self.coordinator.device_id,
                "AUTO",
            )
        elif option == MODE_ON:
            level = self.coordinator.data.get("percentageLevel", 100) or 100
            await self.coordinator.api.set_activation_state(
                self.coordinator.site_id,
                self.coordinator.device_id,
                "MANUAL",
                level=level,
            )
        elif option == MODE_OFF:
            await self.coordinator.api.set_activation_state(
                self.coordinator.site_id,
                self.coordinator.device_id,
                "MANUAL",
                level=0,
            )
        await self.coordinator.async_request_refresh()
