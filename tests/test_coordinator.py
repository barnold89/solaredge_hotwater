"""Tests for the coordinator and its /info refresh."""

from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.solaredge_hotwater.api import ApiError, AuthenticationError
from custom_components.solaredge_hotwater.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    SolarEdgeWarmwaterBinarySensor,
)
from custom_components.solaredge_hotwater.coordinator import (
    HotWaterData,
    SolarEdgeWarmwaterCoordinator,
)

from .common import load_fixture

if TYPE_CHECKING:
    from collections.abc import Iterator

START = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
STATE = {"activationMode": "AUTO", "percentageLevel": 100}


@pytest.fixture
def now() -> Iterator[MagicMock]:
    """Freeze the time the coordinator sees, starting at START."""
    with patch(
        "custom_components.solaredge_hotwater.coordinator.dt_util.utcnow",
        return_value=START,
    ) as utcnow:
        yield utcnow


@pytest.fixture
def api() -> MagicMock:
    """Return an API client that answers with the recorded responses."""
    api = MagicMock()
    api.get_device_info = AsyncMock(
        return_value=load_fixture("info_with_schedule.json")
    )
    api.get_device_state = AsyncMock(return_value=STATE)
    return api


@pytest.fixture
def coordinator(api: MagicMock) -> SolarEdgeWarmwaterCoordinator:
    """Return a coordinator backed by the mocked API client."""
    # The coordinator does not pass config_entry yet (SE-05).
    with patch("homeassistant.helpers.frame.report_usage"):
        return SolarEdgeWarmwaterCoordinator(MagicMock(), api, "site", "device")


def _update(coordinator: SolarEdgeWarmwaterCoordinator) -> HotWaterData:
    """Run one update and store the result like DataUpdateCoordinator does."""
    coordinator.data = asyncio.run(coordinator._async_update_data())
    return coordinator.data


@pytest.mark.usefixtures("now")
@pytest.mark.parametrize(
    "fixture", ["info_with_schedule.json", "info_smart_saver.json"]
)
def test_first_update_fetches_info_and_state(
    coordinator: SolarEdgeWarmwaterCoordinator, api: MagicMock, fixture: str
) -> None:
    """Fetch /info and /state on the first update and keep schedules as sent."""
    info = load_fixture(fixture)
    api.get_device_info.return_value = info

    data = _update(coordinator)

    assert data.state == STATE
    assert data.info == info
    assert data.schedules == info["schedules"]["allSchedules"]
    assert data.last_info_update == START
    assert data.configurations["ratedPower"] == 3000
    assert data.device["type"] == "LEVEL_CTRL"


def test_info_not_fetched_within_interval(
    coordinator: SolarEdgeWarmwaterCoordinator, api: MagicMock, now: MagicMock
) -> None:
    """Fetch only /state until the /info refresh interval has passed."""
    _update(coordinator)
    now.return_value = START + timedelta(minutes=14, seconds=59)

    data = _update(coordinator)

    assert api.get_device_info.await_count == 1
    assert api.get_device_state.await_count == 2
    assert data.last_info_update == START


def test_excess_pv_change_visible_after_info_refresh(
    coordinator: SolarEdgeWarmwaterCoordinator, api: MagicMock, now: MagicMock
) -> None:
    """Show a changed excessPVEnabled once /info is fetched again."""
    description = next(
        d for d in BINARY_SENSOR_DESCRIPTIONS if d.key == "excess_pv_enabled"
    )
    sensor = SolarEdgeWarmwaterBinarySensor(coordinator, description)
    _update(coordinator)
    assert sensor.is_on is True

    info = copy.deepcopy(api.get_device_info.return_value)
    info["deviceConfigurations"]["excessPVEnabled"] = "OFF"
    api.get_device_info.return_value = info

    now.return_value = START + timedelta(minutes=1)
    _update(coordinator)
    assert sensor.is_on is True

    now.return_value = START + timedelta(minutes=15)
    data = _update(coordinator)
    assert sensor.is_on is False
    assert data.last_info_update == now.return_value


def test_write_requests_info_refresh(
    coordinator: SolarEdgeWarmwaterCoordinator, api: MagicMock, now: MagicMock
) -> None:
    """Fetch /info on the next update after a write, then return to the interval."""
    coordinator.async_request_refresh = AsyncMock()
    _update(coordinator)

    asyncio.run(coordinator.async_refresh_after_write())
    now.return_value = START + timedelta(minutes=1)
    data = _update(coordinator)

    coordinator.async_request_refresh.assert_awaited_once()
    assert api.get_device_info.await_count == 2
    assert data.last_info_update == now.return_value

    now.return_value = START + timedelta(minutes=2)
    _update(coordinator)
    assert api.get_device_info.await_count == 2


@pytest.mark.parametrize(
    "error", [ApiError("HTTP 500"), aiohttp.ClientError(), TimeoutError()]
)
def test_info_error_keeps_previous_info(
    coordinator: SolarEdgeWarmwaterCoordinator,
    api: MagicMock,
    now: MagicMock,
    error: Exception,
) -> None:
    """Keep the previous /info on errors and retry on the next update."""
    first = _update(coordinator)
    api.get_device_info.side_effect = error
    api.get_device_state.return_value = {"activationMode": "MANUAL"}

    now.return_value = START + timedelta(minutes=15)
    data = _update(coordinator)

    assert data.state == {"activationMode": "MANUAL"}
    assert data.info == first.info
    assert data.schedules == first.schedules
    assert data.last_info_update == START

    api.get_device_info.side_effect = None
    now.return_value = START + timedelta(minutes=16)
    data = _update(coordinator)

    assert api.get_device_info.await_count == 3
    assert data.last_info_update == now.return_value


def test_info_error_after_write_is_retried(
    coordinator: SolarEdgeWarmwaterCoordinator, api: MagicMock, now: MagicMock
) -> None:
    """Keep the write's /info request pending until a fetch succeeds."""
    coordinator.async_request_refresh = AsyncMock()
    _update(coordinator)
    asyncio.run(coordinator.async_refresh_after_write())

    api.get_device_info.side_effect = ApiError("HTTP 500")
    now.return_value = START + timedelta(minutes=1)
    _update(coordinator)

    api.get_device_info.side_effect = None
    now.return_value = START + timedelta(minutes=2)
    data = _update(coordinator)

    assert api.get_device_info.await_count == 3
    assert data.last_info_update == now.return_value


@pytest.mark.usefixtures("now")
@pytest.mark.parametrize(
    "error", [ApiError("HTTP 500"), aiohttp.ClientError(), TimeoutError()]
)
def test_info_error_on_first_update(
    coordinator: SolarEdgeWarmwaterCoordinator, api: MagicMock, error: Exception
) -> None:
    """Fail the first update when /info cannot be fetched."""
    api.get_device_info.side_effect = error

    with pytest.raises(UpdateFailed):
        _update(coordinator)


def test_info_authentication_error_starts_reauth(
    coordinator: SolarEdgeWarmwaterCoordinator, api: MagicMock, now: MagicMock
) -> None:
    """Start reauth when /info rejects the credentials, even with previous data."""
    _update(coordinator)
    api.get_device_info.side_effect = AuthenticationError
    now.return_value = START + timedelta(minutes=15)

    with pytest.raises(ConfigEntryAuthFailed):
        _update(coordinator)


@pytest.mark.usefixtures("now")
def test_state_error_skips_info(
    coordinator: SolarEdgeWarmwaterCoordinator, api: MagicMock
) -> None:
    """Do not fetch /info when /state already failed."""
    api.get_device_state.side_effect = aiohttp.ClientError()

    with pytest.raises(UpdateFailed):
        _update(coordinator)

    api.get_device_info.assert_not_awaited()
