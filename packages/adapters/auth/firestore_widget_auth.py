from __future__ import annotations

from packages.adapters.firestore.in_memory_stores import InMemoryClientRegistryStore
from packages.core.control_plane.widget_key_hmac import verify_widget_key_hash
from packages.core.ports.auth import AuthProvider
from packages.core.ports.client_registry import ClientRegistryStore
from packages.core.tenant.errors import OriginNotAllowedError, WidgetKeyNotFoundError
from packages.adapters.auth.local_dev_auth import _normalize_origin


class FirestoreWidgetAuthProvider(AuthProvider):
    def __init__(self, registry_store: ClientRegistryStore, *, hash_secret: bytes) -> None:
        self._registry = registry_store
        self._hash_secret = hash_secret

    def reload(self) -> None:
        return None

    def resolve_widget_key(self, public_key: str, origin: str | None) -> str:
        key = (public_key or "").strip()
        if not key:
            raise WidgetKeyNotFoundError("Missing widget key.")

        from packages.core.control_plane.widget_key_hmac import widget_key_lookup_prefix

        prefix = widget_key_lookup_prefix(key)
        candidates = self._registry.find_active_keys_by_prefix(prefix)
        matched_client: str | None = None
        matched_origins: list[str] = []

        for record in candidates:
            if verify_widget_key_hash(key, record.key_hash, secret=self._hash_secret):
                matched_client = record.client_id
                matched_origins = list(record.allowed_origins)
                break

        if not matched_client:
            raise WidgetKeyNotFoundError("Unknown widget key.")

        if matched_origins:
            request_origin = _normalize_origin(origin)
            if not request_origin:
                raise OriginNotAllowedError("Origin header required for this widget key.")
            allowed = {_normalize_origin(o) for o in matched_origins}
            if request_origin not in allowed:
                raise OriginNotAllowedError("Origin not allowed for this widget key.")

        return matched_client
