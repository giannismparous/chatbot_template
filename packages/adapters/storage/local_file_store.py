from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from packages.core.ports.file_store import FileStore, StoredObject
from packages.core.storage.keys import validate_relative_key
from packages.core.tenant.paths import client_root, safe_client_id


class LocalFileStore(FileStore):
    def __init__(self, clients_root: Path) -> None:
        self._clients_root = clients_root.resolve()

    def get_local_clients_root(self) -> Path:
        return self._clients_root

    def _resolve(self, client_id: str, relative_key: str) -> Path:
        cid = safe_client_id(client_id)
        rel = validate_relative_key(relative_key)
        root = client_root(self._clients_root, cid)
        path = (root / rel).resolve()
        if not str(path).startswith(str(root)):
            raise ValueError(f"relative_key escapes tenant root: {relative_key!r}")
        return path

    def exists(self, client_id: str, relative_key: str) -> bool:
        return self._resolve(client_id, relative_key).is_file()

    def read_bytes(self, client_id: str, relative_key: str) -> bytes:
        path = self._resolve(client_id, relative_key)
        if not path.is_file():
            raise FileNotFoundError(relative_key)
        return path.read_bytes()

    def write_bytes(
        self,
        client_id: str,
        relative_key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        _ = content_type
        path = self._resolve(client_id, relative_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def delete(self, client_id: str, relative_key: str) -> None:
        path = self._resolve(client_id, relative_key)
        if path.is_file():
            path.unlink()

    def list_prefix(self, client_id: str, prefix: str) -> list[StoredObject]:
        cid = safe_client_id(client_id)
        rel_prefix = validate_relative_key(prefix) if prefix else ""
        root = client_root(self._clients_root, cid)
        base = (root / rel_prefix).resolve() if rel_prefix else root
        if not str(base).startswith(str(root)):
            raise ValueError(f"prefix escapes tenant root: {prefix!r}")
        if not base.exists():
            return []
        objects: list[StoredObject] = []
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            stat = path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            objects.append(StoredObject(key=rel, size=stat.st_size, updated_at=mtime))
        return objects

    @contextmanager
    def open_local_copy(self, client_id: str, relative_key: str) -> Iterator[Path]:
        path = self._resolve(client_id, relative_key)
        if not path.is_file():
            raise FileNotFoundError(relative_key)
        yield path
