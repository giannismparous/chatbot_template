from __future__ import annotations

from typing import Any

from packages.core.config.loader import TenantConfigLoader
from packages.core.domain.interfaces import ThemeProvider


class TenantThemeProvider(ThemeProvider):
    def __init__(self, config_loader: TenantConfigLoader) -> None:
        self._loader = config_loader

    def get_theme(self, client_id: str) -> dict[str, Any]:
        return dict(self._loader.load(client_id).themes)
