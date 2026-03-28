"""Base entity for SolarEdge Warmwater integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SolarEdgeWarmwaterCoordinator


class SolarEdgeWarmwaterEntity(CoordinatorEntity[SolarEdgeWarmwaterCoordinator]):
    """Base entity for SolarEdge Warmwater devices."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SolarEdgeWarmwaterCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        info = self.coordinator.device_info_data or {}
        device_info = info.get("deviceInfo", {})
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.device_id)},
            name=device_info.get("name", "SolarEdge Warmwater"),
            manufacturer=device_info.get("manufacturer", "SolarEdge"),
            model=device_info.get("model"),
            serial_number=device_info.get("serialNumber"),
        )
