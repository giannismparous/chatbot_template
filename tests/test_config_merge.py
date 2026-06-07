from __future__ import annotations

from pathlib import Path

import pytest

from packages.core.config.merger import deep_merge


def test_deep_merge_client_overrides_win() -> None:
    base = {
        "display_name": "Pack Name",
        "colors": {"primary": "#111111", "secondary": "#222222"},
        "rules": ["pack rule"],
    }
    override = {
        "display_name": "Client Name",
        "colors": {"primary": "#aaaaaa"},
        "rules": ["client rule"],
    }
    merged = deep_merge(base, override)
    assert merged["display_name"] == "Client Name"
    assert merged["colors"]["primary"] == "#aaaaaa"
    assert merged["colors"]["secondary"] == "#222222"
    assert merged["rules"] == ["client rule"]


def test_deep_merge_nested_dicts() -> None:
    base = {"a": {"b": 1, "c": 2}}
    override = {"a": {"c": 3, "d": 4}}
    merged = deep_merge(base, override)
    assert merged == {"a": {"b": 1, "c": 3, "d": 4}}
