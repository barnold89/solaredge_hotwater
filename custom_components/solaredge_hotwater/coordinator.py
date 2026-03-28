"""DataUpdateCoordinator for SolarEdge Warmwater integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthenticationError, SolarEdgeWarmwaterAPI
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class SolarEdgeWarmwaterCoordinator(DataUpdateCoordinator[dict]):
    """Coordinator to fetch data from the SolarEdge API."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: SolarEdgeWarmwaterAPI,
        site_id: str,
        device_id: str,
        scan_interval_seconds: int | None = None,
    ) -> None:
        """Initialize the coordinator."""
        if scan_interval_seconds is not None:
            interval = timedelta(seconds=scan_interval_seconds)
        else:
            interval = DEFAULT_SCAN_INTERVAL
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=interval,
        )
        self.api = api
        self.site_id = site_id
        self.device_id = device_id
        self.device_info_data: dict | None = None

    async def _async_update_data(self) -> dict:
        """Fetch device state from the API."""
        try:
            # Fetch static device info once
            if self.device_info_data is None:
                self.device_info_data = await self.api.get_device_info(
                    self.site_id, self.device_id
                )

            state = await self.api.get_device_state(self.site_id, self.device_id)
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        # Merge device config info into state for sensors that need it
        if self.device_info_data:
            configs = self.device_info_data.get("deviceConfigurations", {})
            state["ratedPower"] = configs.get("ratedPower")
            state["excessPVEnabled"] = configs.get("excessPVEnabled")

        return state
