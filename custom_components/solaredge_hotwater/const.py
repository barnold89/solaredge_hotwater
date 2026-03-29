"""Constants for the SolarEdge Warmwater integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "solaredge_hotwater"

# OAuth2 / Authentication
LOGIN_BASE_URL = "https://login.solaredge.com"
SOLAREDGE_ONE_CLIENT_ID = "ugfnsujd3384sshcjehaphlh3"
MFE_AUTH_PATH = "/mfe/auth/"
MFE_AUTH_CALLBACK_PATH = "/mfe/auth/callback"
TOKEN_PATH = "/oauth2/token"  # noqa: S105

# API
BASE_URL = "https://monitoring.solaredge.com"
DEVICES_LIST_INFO_PATH = "/services/m/so/devices-list/site/{site_id}/info"
DEVICES_LIST_STATE_PATH = "/services/m/so/devices-list/site/{site_id}/state"
DEVICE_INFO_PATH = "/services/m/so/load-device/site/{site_id}/device/{device_id}/info"
DEVICE_STATE_PATH = "/services/m/so/load-device/site/{site_id}/device/{device_id}/state"
DEVICE_ACTIVATION_PATH = (
    "/services/m/api/homeautomation/v1.0/{site_id}/devices/{device_id}/activationState"
)

# HTTP status codes
HTTP_STATUS_OK = 200
HTTP_STATUS_NO_CONTENT = 204
HTTP_STATUS_UNAUTHORIZED = 401
HTTP_STATUS_BAD_REQUEST = 400

# Timeouts
API_TIMEOUT = 30

# Polling
DEFAULT_SCAN_INTERVAL = timedelta(seconds=60)

# Config keys
CONF_SITE_ID = "site_id"
CONF_DEVICE_ID = "device_id"
CONF_SCAN_INTERVAL = "scan_interval"

MIN_SCAN_INTERVAL = 1
MAX_SCAN_INTERVAL = 3600

# Operation modes
MODE_AUTO = "auto"
MODE_ON = "on"
MODE_OFF = "off"
OPERATION_MODES = [MODE_AUTO, MODE_ON, MODE_OFF]

# Platforms
PLATFORMS = [
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]
