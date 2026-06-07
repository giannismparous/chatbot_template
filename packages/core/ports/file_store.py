from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int | None = None
    updated_at: datetime | None = None


class FileStore(ABC):
    """Tenant-scoped blob storage. Keys are relative to clients/{client_id}/."""

    @abstractmethod
    def exists(self, client_id: str, relative_key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def read_bytes(self, client_id: str, relative_key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def write_bytes(
        self,
        client_id: str,
        relative_key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, client_id: str, relative_key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_prefix(self, client_id: str, prefix: str) -> list[StoredObject]:
        raise NotImplementedError

    def read_text(self, client_id: str, relative_key: str, encoding: str = "utf-8") -> str:
        return self.read_bytes(client_id, relative_key).decode(encoding)

    def write_text(
        self,
        client_id: str,
        relative_key: str,
        text: str,
        *,
        encoding: str = "utf-8",
        content_type: str | None = None,
    ) -> None:
        self.write_bytes(
            client_id,
            relative_key,
            text.encode(encoding),
            content_type=content_type or "text/plain; charset=utf-8",
        )

    @abstractmethod
    @contextmanager
    def open_local_copy(self, client_id: str, relative_key: str) -> Iterator[Path]:
        """Yield a local filesystem path for reading (FAISS / large files)."""
        raise NotImplementedError

    @abstractmethod
    def get_local_clients_root(self) -> Path:
        """Local mirror root containing per-tenant subdirectories."""
        raise NotImplementedError
