"""Validates that all JSON files in the integration are well-formed.

Run with: python -m pytest tests/test_json_files.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_INTEGRATION_DIR = Path(__file__).parent.parent / "custom_components" / "clockify_overtime"

_JSON_FILES = [
    _INTEGRATION_DIR / "strings.json",
    _INTEGRATION_DIR / "translations" / "de.json",
    _INTEGRATION_DIR / "translations" / "en.json",
    _INTEGRATION_DIR / "manifest.json",
]


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def test_strings_json_is_valid():
    # SPEC: strings.json must be parseable JSON — HA refuses to load the
    # integration if this file is malformed.
    _load(_JSON_FILES[0])


def test_de_json_is_valid():
    # SPEC: translations/de.json must be parseable JSON.
    _load(_JSON_FILES[1])


def test_en_json_is_valid():
    # SPEC: translations/en.json must be parseable JSON.
    _load(_JSON_FILES[2])


def test_manifest_json_is_valid():
    # SPEC: manifest.json must be parseable JSON — it is the first file HA reads
    # when loading a custom component.
    _load(_JSON_FILES[3])


def test_translation_keys_match_strings():
    # SPEC: Every key present in strings.json must also exist in each translation
    # file so that HA never falls back to raw key names in the UI.
    strings = _load(_JSON_FILES[0])
    for lang_path in (_JSON_FILES[1], _JSON_FILES[2]):
        lang = _load(lang_path)
        _assert_keys_match(strings, lang, lang_path.name)


def _assert_keys_match(reference: dict, target: dict, label: str, path: str = "") -> None:
    for key, value in reference.items():
        full_path = f"{path}.{key}" if path else key
        assert key in target, f"{label}: missing key '{full_path}'"
        if isinstance(value, dict):
            assert isinstance(target[key], dict), (
                f"{label}: key '{full_path}' should be a dict"
            )
            _assert_keys_match(value, target[key], label, full_path)
