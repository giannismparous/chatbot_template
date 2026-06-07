from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from packages.core.ports.file_store import FileStore, StoredObject
from packages.core.storage.keys import validate_relative_key
from packages.core.tenant.paths import safe_client_id


class InMemoryFileStore(FileStore):
    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], tuple[bytes, datetime]] = {}
        self._temp_root = Path("/tmp/inmemory-filestore")

    def get_local_clients_root(self) -> Path:
        return self._temp_root

    def _key(self, client_id: str, relative_key: str) -> tuple[str, str]:
        cid = safe_client_id(client_id)
        rel = validate_relative_key(relative_key)
        return cid, rel

    def exists(self, client_id: str, relative_key: str) -> bool:
        return self._key(client_id, relative_key) in self._objects

    def read_bytes(self, client_id: str, relative_key: str) -> bytes:
        pair = self._key(client_id, relative_key)
        if pair not in self._objects:
            raise FileNotFoundError(relative_key)
        return self._objects[pair][0]

    def write_bytes(
        self,
        client_id: str,
        relative_key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        _ = content_type
        pair = self._key(client_id, relative_key)
        self._objects[pair] = (bytes(data), datetime.now(timezone.utc))

    def delete(self, client_id: str, relative_key: str) -> None:
        self._objects.pop(self._key(client_id, relative_key), None)

    def list_prefix(self, client_id: str, prefix: str) -> list[StoredObject]:
        cid = safe_client_id(client_id)
        rel_prefix = validate_relative_key(prefix) if prefix else ""
        out: list[StoredObject] = []
        for (stored_cid, key), (data, updated) in self._objects.items():
            if stored_cid != cid:
                continue
            if rel_prefix and not key.startswith(rel_prefix):
                continue
            out.append(StoredObject(key=key, size=len(data), updated_at=updated))
        return sorted(out, key=lambda o: o.key)

    @contextmanager
    def open_local_copy(self, client_id: str, relative_key: str) -> Iterator[Path]:
        data = self.read_bytes(client_id, relative_key)
        cid = safe_client_id(client_id)
        rel = validate_relative_key(relative_key)
        path = self._temp_root / cid / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        try:
            yield path
        finally:
            if path.is_file():
                path.unlink(missing_ok=True)
