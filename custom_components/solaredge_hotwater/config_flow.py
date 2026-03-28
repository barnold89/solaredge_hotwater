"""Config flow for SolarEdge Warmwater integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthenticationError, SolarEdgeWarmwaterAPI
from .const import (
    CONF_DEVICE_ID,
    CONF_SCAN_INTERVAL,
    CONF_SITE_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SITE_ID): str,
    }
)


class SolarEdgeWarmwaterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SolarEdge Warmwater."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._username: str = ""
        self._password: str = ""
        self._site_id: str = ""
        self._devices: list[dict] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            self._site_id = user_input[CONF_SITE_ID]

            api = SolarEdgeWarmwaterAPI(
                username=self._username,
                password=self._password,
                session=async_get_clientsession(self.hass),
            )

            try:
                await api.authenticate()
                devices_data = await api.get_devices_info(self._site_id)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during setup")
                errors["base"] = "unknown"
            else:
                # Extract LOAD_DEVICE entries
                load_devices = devices_data.get("devicesByType", {}).get(
                    "LOAD_DEVICE", []
                )
                self._devices = [
                    d for d in load_devices if d.get("deviceInfo", {}).get("deviceId")
                ]

                if not self._devices:
                    errors["base"] = "no_devices"
                elif len(self._devices) == 1:
                    device = self._devices[0]
                    device_id = device["deviceInfo"]["deviceId"]
                    await self.async_set_unique_id(f"{self._site_id}_{device_id}")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=device["deviceInfo"].get("name", "SolarEdge Warmwater"),
                        data={
                            CONF_USERNAME: self._username,
                            CONF_PASSWORD: self._password,
                            CONF_SITE_ID: self._site_id,
                            CONF_DEVICE_ID: device_id,
                        },
                    )
                else:
                    return await self.async_step_select_device()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle device selection when multiple devices are found."""
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            await self.async_set_unique_id(f"{self._site_id}_{device_id}")
            self._abort_if_unique_id_configured()

            # Find device name
            device_name = "SolarEdge Warmwater"
            for d in self._devices:
                if d["deviceInfo"]["deviceId"] == device_id:
                    device_name = d["deviceInfo"].get("name", device_name)
                    break

            return self.async_create_entry(
                title=device_name,
                data={
                    CONF_USERNAME: self._username,
                    CONF_PASSWORD: self._password,
                    CONF_SITE_ID: self._site_id,
                    CONF_DEVICE_ID: device_id,
                },
            )

        device_options = {
            d["deviceInfo"]["deviceId"]: d["deviceInfo"].get(
                "name", d["deviceInfo"]["deviceId"]
            )
            for d in self._devices
        }

        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema(
                {vol.Required(CONF_DEVICE_ID): vol.In(device_options)}
            ),
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return SolarEdgeWarmwaterOptionsFlow(config_entry)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle re-authentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle re-authentication confirmation."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api = SolarEdgeWarmwaterAPI(
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                session=async_get_clientsession(self.hass),
            )

            try:
                await api.authenticate()
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during re-auth")
                errors["base"] = "unknown"
            else:
                entry = self.hass.config_entries.async_get_entry(
                    self.context["entry_id"]
                )
                if entry:
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={
                            **entry.data,
                            CONF_USERNAME: user_input[CONF_USERNAME],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )


class SolarEdgeWarmwaterOptionsFlow(OptionsFlow):
    """Handle options for SolarEdge Warmwater."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                        int, vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                    ),
                }
            ),
        )
