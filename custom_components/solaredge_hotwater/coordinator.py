"""DataUpdateCoordinator for SolarEdge Warmwater integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import SolarEdgeWarmwaterConfigEntry

from .api import ApiError, AuthenticationError, SolarEdgeWarmwaterAPI
from .const import (
    CONF_DEVICE_ID,
    CONF_SCAN_INTERVAL,
    CONF_SITE_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    INFO_REFRESH_INTERVAL,
)

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

    # The entry is always passed, so it is never None as in the base class.
    config_entry: SolarEdgeWarmwaterConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SolarEdgeWarmwaterConfigEntry,
        api: SolarEdgeWarmwaterAPI,
    ) -> None:
        """Initialize the coordinator for the device behind the config entry."""
        seconds = entry.options.get(CONF_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=(
                DEFAULT_SCAN_INTERVAL if seconds is None else timedelta(seconds=seconds)
            ),
        )
        self.api = api
        self.site_id = entry.data[CONF_SITE_ID]
        self.device_id = entry.data[CONF_DEVICE_ID]
        self._info_refresh_requested = False

    async def async_refresh_after_write(self) -> None:
        """Refresh state and device info after a write to the device."""
        self._info_refresh_requested = True
        await self.async_request_refresh()

    async def async_set_activation_state(
        self, mode: str, level: int | None = None
    ) -> None:
        """Switch the device and refresh; raise translated errors on failure."""
        try:
            await self.api.set_activation_state(
                self.site_id, self.device_id, mode, level=level
            )
        except AuthenticationError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except (ApiError, aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="set_state_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.async_refresh_after_write()

    async def _async_update_data(self) -> HotWaterData:
        """Fetch device state and, when due, device info from the API."""
        try:
            state = await self.api.get_device_state(self.site_id, self.device_id)
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except (ApiError, aiohttp.ClientError, TimeoutError) as err:
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
