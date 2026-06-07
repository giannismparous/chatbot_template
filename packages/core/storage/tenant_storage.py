from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from packages.core.ports.file_store import FileStore
from packages.core.storage.keys import join_key, validate_relative_key
from packages.core.tenant.paths import client_root, safe_client_id


class TenantStorage:
    """Facade over FileStore with tenant path helpers and JSON I/O."""

    def __init__(self, file_store: FileStore, *, profile: str = "local") -> None:
        self._file_store = file_store
        self.profile = profile

    @property
    def file_store(self) -> FileStore:
        return self._file_store

    @classmethod
    def local(cls, clients_root: Path) -> TenantStorage:
        from packages.adapters.storage.local_file_store import LocalFileStore

        root = clients_root.resolve()
        return cls(LocalFileStore(root), profile="local")

    @classmethod
    def from_file_store(cls, file_store: FileStore, *, profile: str) -> TenantStorage:
        return cls(file_store, profile=profile)

    def clients_root(self) -> Path:
        return self._file_store.get_local_clients_root()

    def client_dir(self, client_id: str) -> Path:
        cid = safe_client_id(client_id)
        path = client_root(self.clients_root(), cid)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def exists(self, client_id: str, relative_key: str) -> bool:
        return self._file_store.exists(client_id, relative_key)

    def read_bytes(self, client_id: str, relative_key: str) -> bytes:
        return self._file_store.read_bytes(client_id, relative_key)

    def write_bytes(
        self,
        client_id: str,
        relative_key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        self._file_store.write_bytes(client_id, relative_key, data, content_type=content_type)

    def read_text(self, client_id: str, relative_key: str, encoding: str = "utf-8") -> str:
        return self._file_store.read_text(client_id, relative_key, encoding=encoding)

    def write_text(
        self,
        client_id: str,
        relative_key: str,
        text: str,
        *,
        content_type: str | None = None,
    ) -> None:
        self._file_store.write_text(client_id, relative_key, text, content_type=content_type)

    def delete(self, client_id: str, relative_key: str) -> None:
        self._file_store.delete(client_id, relative_key)

    def list_keys(self, client_id: str, prefix: str) -> list[str]:
        rel_prefix = validate_relative_key(prefix) if prefix else ""
        return [obj.key for obj in self._file_store.list_prefix(client_id, rel_prefix)]

    def list_file_keys(self, client_id: str, prefix: str) -> list[str]:
        return self.list_keys(client_id, prefix)

    def read_json(self, client_id: str, relative_key: str) -> dict[str, Any]:
        data = json.loads(self.read_text(client_id, relative_key))
        return data if isinstance(data, dict) else {}

    def write_json(self, client_id: str, relative_key: str, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        self.write_text(client_id, relative_key, text, content_type="application/json")

    def write_json_atomic(self, client_id: str, relative_key: str, payload: dict[str, Any]) -> None:
        self.write_json(client_id, relative_key, payload)

    def ensure_prefix(self, client_id: str, prefix: str) -> None:
        if self.profile == "local":
            path = self.client_dir(client_id) / prefix
            path.mkdir(parents=True, exist_ok=True)

    def local_path(self, client_id: str, relative_key: str) -> Path:
        rel = validate_relative_key(relative_key)
        path = self.client_dir(client_id) / rel
        return path

    def open_local_copy(self, client_id: str, relative_key: str):
        return self._file_store.open_local_copy(client_id, relative_key)

    def remember_active_index_version(self, client_id: str, version_id: str) -> None:
        remember = getattr(self._file_store, "remember_active_index_version", None)
        if callable(remember):
            remember(client_id, version_id)


def join_storage_key(*parts: str) -> str:
    return join_key(*parts)
