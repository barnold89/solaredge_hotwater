"""Tests for the API client's HTTP error handling."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solaredge_hotwater.api import ApiError, SolarEdgeWarmwaterAPI


def _api(status: int) -> SolarEdgeWarmwaterAPI:
    """Return a logged-in API client whose session answers with the given status."""
    session = MagicMock()
    response = session.request.return_value.__aenter__.return_value
    response.status = status
    response.text = AsyncMock(return_value="Internal Server Error")
    api = SolarEdgeWarmwaterAPI("user", "password", session)
    api._access_token = "token"  # noqa: S105
    return api


def test_http_500_on_fetch_raises_api_error() -> None:
    """Turn HTTP 500 on /state into ApiError."""
    with pytest.raises(ApiError, match="500"):
        asyncio.run(_api(500).get_device_state("site", "device"))


def test_http_500_on_switch_raises_api_error() -> None:
    """Turn HTTP 500 on the activation PUT into ApiError."""
    with pytest.raises(ApiError, match="500"):
        asyncio.run(_api(500).set_activation_state("site", "device", "AUTO"))
