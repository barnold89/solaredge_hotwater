"""Shared helpers for the tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from custom_components.solaredge_hotwater.coordinator import HotWaterData

FIXTURES = Path(__file__).parent / "fixtures"

ENTRY_ID = "entry_id"


def load_fixture(name: str) -> dict[str, Any]:
    """Load a recorded API response from tests/fixtures."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_data(
    state: dict[str, Any] | None = None, info: dict[str, Any] | None = None
) -> HotWaterData:
    """Build coordinator data from /state and /info responses."""
    return HotWaterData(
        state=state or {},
        info=info or {},
        schedules=[],
        last_info_update=datetime(2026, 9, 21, tzinfo=UTC),
    )


def mock_hass(entry: MagicMock) -> MagicMock:
    """Return a hass mock whose only known config entry is the given one."""
    hass = MagicMock()
    hass.config_entries.async_get_known_entry.return_value = entry
    return hass
