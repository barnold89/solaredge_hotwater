"""SolarEdge Warmwater integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from .api import AuthenticationError, SolarEdgeWarmwaterAPI
from .const import CONF_DEVICE_ID, CONF_SCAN_INTERVAL, CONF_SITE_ID, PLATFORMS
from .coordinator import SolarEdgeWarmwaterCoordinator

_LOGGER = logging.getLogger(__name__)

type SolarEdgeWarmwaterConfigEntry = ConfigEntry[SolarEdgeWarmwaterCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: SolarEdgeWarmwaterConfigEntry
) -> bool:
    """Set up SolarEdge Warmwater from a config entry."""
    session = async_get_clientsession(hass)
    api = SolarEdgeWarmwaterAPI(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        session=session,
    )

    try:
        await api.authenticate()
    except AuthenticationError as err:
        raise ConfigEntryAuthFailed from err
    except (aiohttp.ClientError, TimeoutError) as err:
        raise ConfigEntryNotReady from err

    site_id = entry.data[CONF_SITE_ID]
    device_id = entry.data[CONF_DEVICE_ID]

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL)
    coordinator = SolarEdgeWarmwaterCoordinator(
        hass, api, site_id, device_id, scan_interval_seconds=scan_interval
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(
    hass: HomeAssistant, entry: SolarEdgeWarmwaterConfigEntry
) -> None:
    """Reload the config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: SolarEdgeWarmwaterConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
