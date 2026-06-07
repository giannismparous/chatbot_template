from __future__ import annotations

from typing import Any, Dict

from packages.config.loaders import load_yaml
from packages.core.domain.interfaces import ThemeProvider


class YamlThemeProvider(ThemeProvider):
    def __init__(self, theme_path: str) -> None:
        self._theme_path = theme_path

    def get_theme(self, client_id: str) -> Dict[str, Any]:
        cfg = load_yaml(self._theme_path)
        defaults = cfg.get("defaults", {})
        clients = cfg.get("clients", {})
        client_theme = clients.get(client_id, {})
        merged = dict(defaults)
        merged.update(client_theme)
        return merged
