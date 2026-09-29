"""Tests for the entity icons in icons.json."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from custom_components.solaredge_hotwater.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
)
from custom_components.solaredge_hotwater.const import OPERATION_MODES
from custom_components.solaredge_hotwater.select import SolarEdgeOperationMode
from custom_components.solaredge_hotwater.sensor import SENSOR_DESCRIPTIONS

INTEGRATION = Path(__file__).parents[1] / "custom_components" / "solaredge_hotwater"


def _load(name: str) -> dict:
    """Load a JSON file from the integration folder."""
    return json.loads((INTEGRATION / name).read_text(encoding="utf-8"))


def _entities_without_device_class() -> dict[str, set[str]]:
    """Return the translation keys per platform that need an icon from icons.json."""
    # Entities with a device class get their icon from Home Assistant
    return {
        "sensor": {
            d.translation_key for d in SENSOR_DESCRIPTIONS if not d.device_class
        },
        "binary_sensor": {
            d.translation_key for d in BINARY_SENSOR_DESCRIPTIONS if not d.device_class
        },
        "select": {SolarEdgeOperationMode(MagicMock()).translation_key},
    }


def test_every_entity_keeps_its_icon() -> None:
    """Give every entity without a device class a default icon."""
    icons = _load("icons.json")["entity"]

    for platform, keys in _entities_without_device_class().items():
        for key in keys:
            assert icons[platform][key]["default"].startswith("mdi:"), key


def test_icons_match_translations() -> None:
    """Map icons only to translation keys that exist in every language."""
    icons = _load("icons.json")["entity"]

    for language in ("en.json", "de.json"):
        entities = _load(f"translations/{language}")["entity"]
        for platform, keys in icons.items():
            assert set(keys) <= set(entities[platform]), (language, platform)


def test_operation_mode_icons_per_state() -> None:
    """Give every operation mode its own icon."""
    states = _load("icons.json")["entity"]["select"]["operation_mode"]["state"]

    assert set(states) == set(OPERATION_MODES)
    assert len(set(states.values())) == len(OPERATION_MODES)
