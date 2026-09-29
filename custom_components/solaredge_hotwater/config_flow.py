"""Config flow for SolarEdge Warmwater integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

if TYPE_CHECKING:
    from collections.abc import Mapping

from .api import AuthenticationError, LoginUnavailableError, SolarEdgeWarmwaterAPI
from .const import (
    CONF_DEVICE_ID,
    CONF_SCAN_INTERVAL,
    CONF_SITE_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    SHORT_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _scan_interval(options: Mapping[str, Any]) -> int:
    """Return the polling interval in seconds from the options."""
    return options.get(CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds()))


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

    async def _async_validate(
        self, username: str, password: str, site_id: str | None = None
    ) -> str | None:
        """
        Log in and, given a site ID, fetch the water heaters of that site.

        Store the devices that carry a device ID in self._devices and return
        the error key for the form, or None on success.
        """
        api = SolarEdgeWarmwaterAPI(
            username=username,
            password=password,
            session=async_get_clientsession(self.hass),
        )

        try:
            await api.authenticate()
            if site_id is None:
                return None
            devices_data = await api.get_devices_info(site_id)
        except AuthenticationError:
            return "invalid_auth"
        except LoginUnavailableError, aiohttp.ClientError, TimeoutError:
            return "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error while validating the credentials")
            return "unknown"

        # Extract LOAD_DEVICE entries
        load_devices = devices_data.get("devicesByType", {}).get("LOAD_DEVICE", [])
        self._devices = [
            d for d in load_devices if d.get("deviceInfo", {}).get("deviceId")
        ]
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            self._site_id = user_input[CONF_SITE_ID]

            error = await self._async_validate(
                self._username, self._password, self._site_id
            )
            if error:
                errors["base"] = error
            elif not self._devices:
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
    def async_get_options_flow(
        config_entry: ConfigEntry,  # noqa: ARG004
    ) -> SolarEdgeWarmwaterOptionsFlow:
        """Return the options flow handler."""
        return SolarEdgeWarmwaterOptionsFlow()

    async def async_step_reauth(
        self, _entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication after SolarEdge rejected the credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password of the configured account and verify it."""
        entry = self._get_reauth_entry()
        username = entry.data[CONF_USERNAME]
        errors: dict[str, str] = {}

        if user_input is not None:
            error = await self._async_validate(username, user_input[CONF_PASSWORD])
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={CONF_USERNAME: username},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """
        Change the account, password or site ID of the configured entry.

        The password field starts empty; left empty, the stored password is
        kept. The site must still hold the entry's water heater and the unique
        ID `{site_id}_{device_id}` must not change, otherwise the flow aborts.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input.get(CONF_PASSWORD) or entry.data[CONF_PASSWORD]
            site_id = user_input[CONF_SITE_ID]

            error = await self._async_validate(username, password, site_id)
            if error:
                errors["base"] = error
            elif not self._devices:
                errors["base"] = "no_devices"
            else:
                device_id = entry.data[CONF_DEVICE_ID]
                if any(d["deviceInfo"]["deviceId"] == device_id for d in self._devices):
                    await self.async_set_unique_id(f"{site_id}_{device_id}")
                else:
                    # The site lacks this water heater; switching to another
                    # device would change the unique ID.
                    await self.async_set_unique_id(None)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_SITE_ID: site_id,
                    },
                )

        defaults = user_input or entry.data
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=defaults[CONF_USERNAME]): str,
                    vol.Optional(CONF_PASSWORD): str,
                    vol.Required(CONF_SITE_ID, default=defaults[CONF_SITE_ID]): str,
                }
            ),
            errors=errors,
        )


class SolarEdgeWarmwaterOptionsFlow(OptionsFlowWithReload):
    """Handle options for SolarEdge Warmwater."""

    # Set in async_step_init, read by the confirmation steps.
    _pending: dict[str, Any]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            current = _scan_interval(self.config_entry.options)
            # Ask only when entering the short range; staying in it needs no
            # new confirmation.
            if user_input[CONF_SCAN_INTERVAL] < SHORT_SCAN_INTERVAL <= current:
                self._pending = user_input
                return await self.async_step_confirm_interval()
            return self.async_create_entry(data=user_input)

        return self._show_init_form(self.config_entry.options)

    async def async_step_confirm_interval(
        self, _user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Warn about a short polling interval before saving it."""
        return self.async_show_menu(
            step_id="confirm_interval",
            menu_options=["save_interval", "change_interval"],
            description_placeholders={
                "scan_interval": str(self._pending[CONF_SCAN_INTERVAL])
            },
        )

    async def async_step_save_interval(
        self, _user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Save the confirmed short polling interval."""
        return self.async_create_entry(data=self._pending)

    async def async_step_change_interval(
        self, _user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options again with the saved interval, or the default."""
        saved = _scan_interval(self.config_entry.options)
        return self._show_init_form({**self._pending, CONF_SCAN_INTERVAL: saved})

    def _show_init_form(self, defaults: Mapping[str, Any]) -> ConfigFlowResult:
        """Show the options form prefilled with the given values."""
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=_scan_interval(defaults)
                    ): vol.All(
                        int, vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                    ),
                }
            ),
        )
