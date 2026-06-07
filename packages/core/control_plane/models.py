from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class WidgetKeyRecord:
    key_id: str
    client_id: str
    key_prefix: str
    key_hash: str
    hash_alg: str
    allowed_origins: list[str]
    status: str
    created_at: datetime
    revoked_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "client_id": self.client_id,
            "key_prefix": self.key_prefix,
            "key_hash": self.key_hash,
            "hash_alg": self.hash_alg,
            "allowed_origins": list(self.allowed_origins),
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, client_id: str) -> WidgetKeyRecord:
        created = datetime.fromisoformat(str(data["created_at"]))
        revoked_raw = data.get("revoked_at")
        revoked = datetime.fromisoformat(str(revoked_raw)) if revoked_raw else None
        return cls(
            key_id=str(data["key_id"]),
            client_id=client_id,
            key_prefix=str(data["key_prefix"]),
            key_hash=str(data["key_hash"]),
            hash_alg=str(data.get("hash_alg") or "hmac-sha256-v1"),
            allowed_origins=list(data.get("allowed_origins") or []),
            status=str(data.get("status") or "active"),
            created_at=created,
            revoked_at=revoked,
        )


@dataclass
class ClientRecord:
    client_id: str
    display_name: str
    status: str
    domain_pack: str
    config_revision: int
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "display_name": self.display_name,
            "status": self.status,
            "domain_pack": self.domain_pack,
            "config_revision": self.config_revision,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class ConfigMetaRecord:
    client_id: str
    config_key: str
    storage_key: str
    content_sha256: str
    size_bytes: int
    content_type: str
    revision: int
    updated_at: datetime
    updated_by: str = "platform_admin"

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "config_key": self.config_key,
            "storage_key": self.storage_key,
            "content_sha256": self.content_sha256,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
            "revision": self.revision,
            "updated_at": self.updated_at.isoformat(),
            "updated_by": self.updated_by,
        }


@dataclass
class CreateClientResult:
    client_id: str
    display_name: str
    domain_pack: str
    widget_key_prefix: str
    allowed_origins: list[str]
    widget_key: str | None = None


@dataclass
class RotateWidgetKeyResult:
    client_id: str
    key_id: str
    widget_key_prefix: str
    allowed_origins: list[str]
    widget_key: str
    revoked_key_id: str | None = None


@dataclass
class AdminUserRecord:
    """Scaffold only — Phase 21 Firebase Auth."""

    uid: str
    email: str
    roles: list[str] = field(default_factory=lambda: ["platform_admin"])
    client_scopes: list[str] = field(default_factory=list)
    status: str = "active"
