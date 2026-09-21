"""Tests for the operation mode select entity."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solaredge_hotwater.const import MODE_AUTO, MODE_OFF, MODE_ON
from custom_components.solaredge_hotwater.select import SolarEdgeOperationMode

from .common import make_data


def _entity(data: dict[str, Any]) -> SolarEdgeOperationMode:
    """Create a select entity backed by a mocked coordinator."""
    coordinator = MagicMock()
    coordinator.data = make_data(state=data)
    coordinator.site_id = "site"
    coordinator.device_id = "device"
    return SolarEdgeOperationMode(coordinator)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"activationMode": "MANUAL", "percentageLevel": None}, MODE_OFF),
        ({"activationMode": "MANUAL"}, MODE_OFF),
        ({"activationMode": "MANUAL", "percentageLevel": 0}, MODE_OFF),
        ({"activationMode": "MANUAL", "percentageLevel": 100}, MODE_ON),
        ({"activationMode": "MANUAL", "percentageLevel": "100"}, MODE_ON),
        ({"activationMode": "MANUAL", "percentageLevel": "abc"}, MODE_OFF),
        ({"activationMode": "AUTO", "percentageLevel": None}, MODE_AUTO),
        ({"activationMode": None, "percentageLevel": 100}, MODE_OFF),
        ({"percentageLevel": 100}, MODE_OFF),
        ({"activationMode": "BOOST", "percentageLevel": 100}, MODE_OFF),
    ],
)
def test_current_option(data: dict[str, Any], expected: str) -> None:
    """Map activationMode and percentageLevel to an option without raising."""
    assert _entity(data).current_option == expected


def test_select_option_requests_info_refresh() -> None:
    """Refresh state and device info after switching the mode."""
    entity = _entity({})
    entity.coordinator.api.set_activation_state = AsyncMock()
    entity.coordinator.async_refresh_after_write = AsyncMock()

    asyncio.run(entity.async_select_option(MODE_ON))

    entity.coordinator.api.set_activation_state.assert_awaited_once_with(
        "site", "device", "MANUAL", level=100
    )
    entity.coordinator.async_refresh_after_write.assert_awaited_once()
