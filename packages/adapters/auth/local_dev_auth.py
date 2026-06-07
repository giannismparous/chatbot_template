from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from packages.core.admin.widget_keys import widget_key_matches
from packages.core.ports.auth import AuthProvider
from packages.core.ports.config_store import ConfigStore
from packages.core.tenant.errors import OriginNotAllowedError, WidgetKeyNotFoundError
from packages.core.tenant.paths import safe_client_id


def _normalize_origin(origin: str | None) -> str | None:
    if not origin:
        return None
    value = origin.strip()
    if not value:
        return None
    if "://" not in value:
        return value.rstrip("/").lower()
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return value.rstrip("/").lower()
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}".lower()


class LocalDevAuthProvider(AuthProvider):
    def __init__(self, config_store: ConfigStore) -> None:
        self._config_store = config_store
        self._entries: list[tuple[str, list[str], dict[str, Any]]] | None = None

    def _load_entries(self) -> list[tuple[str, list[str], dict[str, Any]]]:
        if self._entries is not None:
            return self._entries

        registry = self._config_store.load_registry()
        clients = registry.get("clients") or {}
        entries: list[tuple[str, list[str], dict[str, Any]]] = []

        for client_id, entry in clients.items():
            if not isinstance(entry, dict):
                continue
            cid = safe_client_id(str(client_id))
            for key_entry in entry.get("widget_keys") or []:
                if not isinstance(key_entry, dict):
                    continue
                if not key_entry.get("public_key") and not key_entry.get("public_key_hash"):
                    continue
                origins = [
                    _normalize_origin(str(o))
                    for o in (key_entry.get("allowed_origins") or [])
                    if str(o).strip()
                ]
                origins = [o for o in origins if o]
                entries.append((cid, origins, key_entry))

        self._entries = entries
        return entries

    def reload(self) -> None:
        self._entries = None

    def resolve_widget_key(self, public_key: str, origin: str | None) -> str:
        key = (public_key or "").strip()
        if not key:
            raise WidgetKeyNotFoundError("Missing widget key.")

        matched: tuple[str, list[str]] | None = None
        for client_id, allowed_origins, key_entry in self._load_entries():
            if widget_key_matches(key_entry, key):
                matched = (client_id, allowed_origins)
                break

        if not matched:
            raise WidgetKeyNotFoundError("Unknown widget key.")

        client_id, allowed_origins = matched
        if allowed_origins:
            request_origin = _normalize_origin(origin)
            if not request_origin:
                raise OriginNotAllowedError("Origin header required for this widget key.")
            allowed = {_normalize_origin(o) for o in allowed_origins}
            if request_origin not in allowed:
                raise OriginNotAllowedError("Origin not allowed for this widget key.")

        return client_id
