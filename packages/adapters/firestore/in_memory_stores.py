from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from packages.core.control_plane.models import (
    ConfigMetaRecord,
    CreateClientResult,
    RotateWidgetKeyResult,
    WidgetKeyRecord,
)
from packages.core.control_plane.widget_key_hmac import (
    HASH_ALG,
    compute_widget_key_hash,
    generate_widget_key,
    sanitize_widget_key_meta,
    widget_key_display_prefix,
)
from packages.core.jobs.models import JobRecord, utc_now
from packages.core.ports.client_registry import ClientRegistryStore
from packages.core.ports.config_meta_store import ConfigMetaStore
from packages.core.ports.job_store import JobStore
from packages.core.tenant.paths import safe_client_id

from packages.adapters.firestore.in_memory_backend import InMemoryFirestoreBackend


class InMemoryClientRegistryStore(ClientRegistryStore):
    def __init__(self, backend: InMemoryFirestoreBackend, *, hash_secret: bytes) -> None:
        self._backend = backend
        self._hash_secret = hash_secret

    def list_clients(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for client_id in self._backend.list_client_ids():
            out.append(self.get_client(client_id))
        return out

    def get_client(self, client_id: str) -> dict[str, Any]:
        cid = safe_client_id(client_id)
        doc = self._backend.get_client(cid)
        if not doc:
            raise ValueError(f"Client not found: {cid}")
        return {
            "client_id": cid,
            "display_name": doc.get("display_name"),
            "widget_keys": self.list_widget_keys(cid),
            "has_config": True,
            "config_revision": int(doc.get("config_revision") or 0),
        }

    def client_exists(self, client_id: str) -> bool:
        cid = safe_client_id(client_id)
        return self._backend.get_client(cid) is not None

    def create_client_record(
        self,
        *,
        client_id: str,
        display_name: str,
        domain_pack: str,
        allowed_origins: list[str] | None,
        reveal_widget_key: bool,
    ) -> CreateClientResult:
        cid = safe_client_id(client_id)
        if self.client_exists(cid):
            raise ValueError(f"Client already exists: {cid}")
        now = datetime.now(timezone.utc)
        self._backend.upsert_client(
            cid,
            {
                "client_id": cid,
                "display_name": display_name,
                "status": "active",
                "domain_pack": safe_client_id(domain_pack),
                "config_revision": 0,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        )
        full_key, prefix, key_hash = generate_widget_key_with_secret(self._hash_secret)
        key_id = f"{cid}_widget_1"
        self._backend.upsert_widget_key(
            cid,
            key_id,
            {
                "key_id": key_id,
                "key_prefix": prefix,
                "key_hash": key_hash,
                "hash_alg": HASH_ALG,
                "allowed_origins": list(allowed_origins or []),
                "status": "active",
                "created_at": now.isoformat(),
                "revoked_at": None,
            },
        )
        return CreateClientResult(
            client_id=cid,
            display_name=display_name,
            domain_pack=safe_client_id(domain_pack),
            widget_key_prefix=widget_key_display_prefix(full_key),
            allowed_origins=list(allowed_origins or []),
            widget_key=full_key if reveal_widget_key else None,
        )

    def list_widget_keys(self, client_id: str) -> list[dict[str, Any]]:
        cid = safe_client_id(client_id)
        docs = self._backend.list_widget_keys(cid)
        sanitized = [sanitize_widget_key_meta(doc) for doc in docs]
        return sorted(sanitized, key=lambda item: str(item.get("created_at") or ""), reverse=True)

    def rotate_widget_key(
        self,
        client_id: str,
        *,
        allowed_origins: list[str] | None = None,
        revoke_key_id: str | None = None,
    ) -> RotateWidgetKeyResult:
        cid = safe_client_id(client_id)
        if not self.client_exists(cid):
            raise ValueError(f"Client not found: {cid}")
        existing = self._backend.list_widget_keys(cid)
        active = [doc for doc in existing if doc.get("status") == "active"]
        revoked_id: str | None = None
        if revoke_key_id:
            self.revoke_widget_key(cid, revoke_key_id)
            revoked_id = revoke_key_id
        elif active:
            old_id = str(active[0]["key_id"])
            self.revoke_widget_key(cid, old_id)
            revoked_id = old_id
        origins = list(allowed_origins or [])
        if not origins and active:
            origins = list(active[0].get("allowed_origins") or [])
        full_key, prefix, key_hash = generate_widget_key_with_secret(self._hash_secret)
        now = datetime.now(timezone.utc)
        key_id = f"{cid}_widget_{len(existing) + 1}"
        self._backend.upsert_widget_key(
            cid,
            key_id,
            {
                "key_id": key_id,
                "key_prefix": prefix,
                "key_hash": key_hash,
                "hash_alg": HASH_ALG,
                "allowed_origins": origins,
                "status": "active",
                "created_at": now.isoformat(),
                "revoked_at": None,
            },
        )
        return RotateWidgetKeyResult(
            client_id=cid,
            key_id=key_id,
            widget_key_prefix=widget_key_display_prefix(full_key),
            allowed_origins=origins,
            widget_key=full_key,
            revoked_key_id=revoked_id,
        )

    def revoke_widget_key(self, client_id: str, key_id: str) -> None:
        cid = safe_client_id(client_id)
        doc = self._backend.get_widget_key(cid, key_id)
        if not doc:
            raise ValueError(f"Widget key not found: {key_id}")
        doc["status"] = "revoked"
        doc["revoked_at"] = datetime.now(timezone.utc).isoformat()
        self._backend.upsert_widget_key(cid, key_id, doc)

    def find_active_keys_by_prefix(self, prefix: str) -> list[WidgetKeyRecord]:
        return self._backend.query_widget_keys_by_prefix(prefix, status="active")

    def increment_config_revision(self, client_id: str) -> int:
        cid = safe_client_id(client_id)
        doc = self._backend.get_client(cid)
        if not doc:
            raise ValueError(f"Client not found: {cid}")
        revision = int(doc.get("config_revision") or 0) + 1
        doc["config_revision"] = revision
        doc["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._backend.upsert_client(cid, doc)
        return revision

    def get_config_revision(self, client_id: str) -> int:
        cid = safe_client_id(client_id)
        doc = self._backend.get_client(cid)
        if not doc:
            return 0
        return int(doc.get("config_revision") or 0)


def generate_widget_key_with_secret(secret: bytes) -> tuple[str, str, str]:
    from packages.core.control_plane.widget_key_hmac import widget_key_lookup_prefix
    import secrets

    suffix = secrets.token_urlsafe(24)
    full = f"wk_{suffix}"
    prefix = widget_key_lookup_prefix(full)
    key_hash = compute_widget_key_hash(full, secret=secret)
    return full, prefix, key_hash


class InMemoryConfigMetaStore(ConfigMetaStore):
    def __init__(self, backend: InMemoryFirestoreBackend) -> None:
        self._backend = backend

    def get_meta(self, client_id: str, config_key: str) -> ConfigMetaRecord | None:
        cid = safe_client_id(client_id)
        doc = self._backend.get_config_meta(cid, config_key)
        if not doc:
            return None
        return ConfigMetaRecord(
            client_id=cid,
            config_key=str(doc["config_key"]),
            storage_key=str(doc["storage_key"]),
            content_sha256=str(doc["content_sha256"]),
            size_bytes=int(doc["size_bytes"]),
            content_type=str(doc["content_type"]),
            revision=int(doc["revision"]),
            updated_at=datetime.fromisoformat(str(doc["updated_at"])),
            updated_by=str(doc.get("updated_by") or "platform_admin"),
        )

    def put_meta(self, record: ConfigMetaRecord) -> None:
        self._backend.upsert_config_meta(record.client_id, record.config_key, record.to_dict())

    def list_meta(self, client_id: str) -> list[ConfigMetaRecord]:
        cid = safe_client_id(client_id)
        out: list[ConfigMetaRecord] = []
        for doc in self._backend.list_config_meta(cid):
            meta = self.get_meta(cid, str(doc["config_key"]))
            if meta:
                out.append(meta)
        return out


class InMemoryJobStore(JobStore):
    def __init__(self, backend: InMemoryFirestoreBackend) -> None:
        self._backend = backend

    def create(self, record: JobRecord) -> JobRecord:
        self._backend.upsert_job(record.client_id, record.job_id, record.to_dict())
        return record

    def update(self, record: JobRecord) -> None:
        record.updated_at = utc_now()
        self._backend.upsert_job(record.client_id, record.job_id, record.to_dict())

    def get(self, client_id: str, job_id: str) -> JobRecord | None:
        cid = safe_client_id(client_id)
        doc = self._backend.get_job(cid, job_id)
        if not doc:
            return None
        return JobRecord.from_dict(doc)

    def list_jobs(self, client_id: str, *, limit: int = 50) -> list[JobRecord]:
        cid = safe_client_id(client_id)
        return [JobRecord.from_dict(doc) for doc in self._backend.list_jobs(cid, limit=limit)]
