"""DataUpdateCoordinator for SolarEdge Warmwater integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from .api import ApiError, AuthenticationError, SolarEdgeWarmwaterAPI
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, INFO_REFRESH_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HotWaterData:
    """Device data from the /state and /info endpoints."""

    state: dict[str, Any]
    info: dict[str, Any]
    schedules: list[dict[str, Any]]
    last_info_update: datetime

    @property
    def measurements(self) -> dict[str, Any]:
        """Return the measurements from /state."""
        return self.state.get("measurements") or {}

    @property
    def device(self) -> dict[str, Any]:
        """Return the device info from /info."""
        return self.info.get("deviceInfo") or {}

    @property
    def configurations(self) -> dict[str, Any]:
        """Return the device configurations from /info."""
        return self.info.get("deviceConfigurations") or {}


def _schedules(info: dict[str, Any]) -> list[dict[str, Any]]:
    """Return all schedules from /info; null or missing fields count as none."""
    return (info.get("schedules") or {}).get("allSchedules") or []


class SolarEdgeWarmwaterCoordinator(DataUpdateCoordinator[HotWaterData]):
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
        self._info_refresh_requested = False

    async def async_refresh_after_write(self) -> None:
        """Refresh state and device info after a write to the device."""
        self._info_refresh_requested = True
        await self.async_request_refresh()

    async def _async_update_data(self) -> HotWaterData:
        """Fetch device state and, when due, device info from the API."""
        try:
            state = await self.api.get_device_state(self.site_id, self.device_id)
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except (aiohttp.ClientError, TimeoutError) as err:
            msg = f"Error communicating with API: {err}"
            raise UpdateFailed(msg) from err

        info, last_info_update = await self._async_fetch_info()
        return HotWaterData(
            state=state or {},
            info=info,
            schedules=_schedules(info),
            last_info_update=last_info_update,
        )

    async def _async_fetch_info(self) -> tuple[dict[str, Any], datetime]:
        """
        Return device info and its fetch time.

        /info is fetched on the first update, after a write and every
        INFO_REFRESH_INTERVAL. If it fails, the previous info is kept and the
        fetch is retried on the next update.
        """
        previous = self.data
        if (
            previous is not None
            and not self._info_refresh_requested
            and dt_util.utcnow() - previous.last_info_update < INFO_REFRESH_INTERVAL
        ):
            return previous.info, previous.last_info_update

        try:
            info = await self.api.get_device_info(self.site_id, self.device_id)
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except (ApiError, aiohttp.ClientError, TimeoutError) as err:
            if previous is None:
                msg = f"Error communicating with API: {err}"
                raise UpdateFailed(msg) from err
            _LOGGER.warning(
                "Error fetching device info, keeping previous data: %s", err
            )
            return previous.info, previous.last_info_update

        self._info_refresh_requested = False
        return info or {}, dt_util.utcnow()
