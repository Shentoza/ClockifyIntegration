"""Stub out the homeassistant package so calculations.py can be imported
without a running HA instance or the homeassistant pip package."""
import sys
from unittest.mock import MagicMock

_HA_MODULES = [
    "aiohttp",
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.const",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.selector",
    "homeassistant.helpers.entity_platform",
    "homeassistant.components",
    "homeassistant.components.number",
    "homeassistant.components.sensor",
]

for _mod in _HA_MODULES:
    sys.modules.setdefault(_mod, MagicMock())
