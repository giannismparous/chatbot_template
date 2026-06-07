from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from packages.core.ports.file_store import FileStore
from packages.core.storage.keys import gcs_object_name, validate_relative_key
from packages.core.tenant.paths import safe_client_id


class GcsFileStore(FileStore):
    """Write-through local cache backed by a private GCS bucket."""

    def __init__(
        self,
        *,
        bucket_name: str,
        cache_root: Path,
        client: Any | None = None,
    ) -> None:
        self._bucket_name = bucket_name.strip()
        if not self._bucket_name:
            raise ValueError("GCS bucket name is required.")
        self._cache_root = cache_root.resolve()
        self._cache_root.mkdir(parents=True, exist_ok=True)
        self._client = client
        self._local_version_cache: dict[tuple[str, str], str] = {}

    @property
    def bucket_name(self) -> str:
        return self._bucket_name

    def _storage_client(self) -> Any:
        if self._client is not None:
            return self._client
        from google.cloud import storage

        return storage.Client()

    def _bucket(self) -> Any:
        return self._storage_client().bucket(self._bucket_name)

    def get_local_clients_root(self) -> Path:
        return self._cache_root

    def _cache_path(self, client_id: str, relative_key: str) -> Path:
        cid = safe_client_id(client_id)
        rel = validate_relative_key(relative_key)
        root = (self._cache_root / cid).resolve()
        path = (root / rel).resolve()
        if not str(path).startswith(str(root)):
            raise ValueError(f"relative_key escapes tenant cache: {relative_key!r}")
        return path

    def _download_if_needed(self, client_id: str, relative_key: str) -> Path:
        path = self._cache_path(client_id, relative_key)
        if path.is_file():
            return path
        blob_name = gcs_object_name(client_id, relative_key)
        blob = self._bucket().blob(blob_name)
        if not blob.exists():
            raise FileNotFoundError(relative_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(path))
        return path

    def exists(self, client_id: str, relative_key: str) -> bool:
        path = self._cache_path(client_id, relative_key)
        if path.is_file():
            return True
        blob = self._bucket().blob(gcs_object_name(client_id, relative_key))
        return bool(blob.exists())

    def read_bytes(self, client_id: str, relative_key: str) -> bytes:
        return self._download_if_needed(client_id, relative_key).read_bytes()

    def write_bytes(
        self,
        client_id: str,
        relative_key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        path = self._cache_path(client_id, relative_key)
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
        blob = self._bucket().blob(gcs_object_name(client_id, relative_key))
        blob.upload_from_string(data, content_type=content_type or "application/octet-stream")
        cache_key = (safe_client_id(client_id), validate_relative_key(relative_key))
        if cache_key in self._local_version_cache:
            del self._local_version_cache[cache_key]

    def delete(self, client_id: str, relative_key: str) -> None:
        path = self._cache_path(client_id, relative_key)
        if path.is_file():
            path.unlink()
        blob = self._bucket().blob(gcs_object_name(client_id, relative_key))
        if blob.exists():
            blob.delete()

    def list_prefix(self, client_id: str, prefix: str) -> list:
        from packages.core.ports.file_store import StoredObject

        cid = safe_client_id(client_id)
        rel_prefix = validate_relative_key(prefix) if prefix else ""
        gcs_prefix = gcs_object_name(cid, rel_prefix) if rel_prefix else gcs_object_name(cid, ".")
        if gcs_prefix.endswith("/."):
            gcs_prefix = gcs_object_name(cid, "")
        tenant_prefix = f"clients/{cid}/"
        if rel_prefix:
            tenant_prefix = f"{tenant_prefix}{rel_prefix}"
        objects: list[StoredObject] = []
        for blob in self._bucket().list_blobs(prefix=tenant_prefix):
            name = blob.name
            if not name.startswith(tenant_prefix):
                continue
            rel = name[len(f"clients/{cid}/") :]
            if not rel or rel.endswith("/"):
                continue
            updated = blob.updated
            if updated and updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            objects.append(
                StoredObject(
                    key=rel,
                    size=blob.size,
                    updated_at=updated,
                )
            )
        return sorted(objects, key=lambda item: item.key)

    @contextmanager
    def open_local_copy(self, client_id: str, relative_key: str) -> Iterator[Path]:
        rel = validate_relative_key(relative_key)
        cache_key = (safe_client_id(client_id), rel)
        version_hint = self._local_version_cache.get(cache_key)
        path = self._cache_path(client_id, rel)
        if path.is_file() and version_hint:
            yield path
            return
        path = self._download_if_needed(client_id, rel)
        yield path

    def remember_active_index_version(self, client_id: str, version_id: str) -> None:
        cid = safe_client_id(client_id)
        prefix = f"indexes/versions/{version_id}/"
        for name in ("knowledge_index.json", "vector_index.json"):
            self._local_version_cache[(cid, prefix + name)] = version_id
