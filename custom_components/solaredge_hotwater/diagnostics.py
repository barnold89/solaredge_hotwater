"""Diagnostics support for the SolarEdge Warmwater integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from .const import CONF_DEVICE_ID, CONF_SITE_ID

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import SolarEdgeWarmwaterConfigEntry

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_SITE_ID,
    CONF_DEVICE_ID,
    "siteId",
    "deviceId",
    "serialNumber",
    "access_token",
    "refresh_token",
    "accessToken",
    "refreshToken",
    "token",
}


def _redact_text(text: str, secrets: list[str]) -> str:
    """Replace the secret values in free text such as an error message."""
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    return text


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,  # noqa: ARG001
    entry: SolarEdgeWarmwaterConfigEntry,
) -> dict[str, Any]:
    """Return the raw API responses, options and coordinator status."""
    coordinator = entry.runtime_data
    data = coordinator.data

    # Error messages contain the request path with site and device ID, so the
    # identifiers are also removed from the text of the last exception
    secrets = [
        str(value)
        for value in (
            entry.data.get(CONF_USERNAME),
            coordinator.site_id,
            coordinator.device_id,
            data.device.get("serialNumber") if data else None,
        )
        if value
    ]
    last_exception = coordinator.last_exception

    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": (
                _redact_text(repr(last_exception), secrets) if last_exception else None
            ),
            "failed_state_updates": coordinator.failed_state_updates,
            "update_interval": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "last_info_update": data.last_info_update.isoformat() if data else None,
        },
        "state": async_redact_data(data.state, TO_REDACT) if data else None,
        "info": async_redact_data(data.info, TO_REDACT) if data else None,
    }
