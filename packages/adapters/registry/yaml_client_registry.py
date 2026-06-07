from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from packages.config.loaders import load_yaml, save_yaml
from packages.core.admin.widget_keys import (
    build_registry_key_entry,
    generate_widget_key,
    sanitize_registry_client,
    sanitize_widget_key_entry,
)
from packages.core.control_plane.models import CreateClientResult
from packages.core.control_plane.widget_key_hmac import sanitize_widget_key_meta
from packages.core.jobs.models import JobRecord, JobStatus, JobType, utc_now
from packages.core.ports.client_registry import ClientRegistryStore
from packages.core.tenant.paths import safe_client_id


class YamlClientRegistryStore(ClientRegistryStore):
    """Local profile registry backed by YAML file (dev plaintext allowed)."""

    def __init__(self, *, clients_root: Path, registry_path: Path) -> None:
        self._clients_root = clients_root.resolve()
        self._registry_path = registry_path.resolve()

    def _load(self) -> dict[str, Any]:
        if not self._registry_path.is_file():
            return {"clients": {}}
        data = load_yaml(str(self._registry_path))
        return data if isinstance(data, dict) else {"clients": {}}

    def _save(self, registry: dict[str, Any]) -> None:
        save_yaml(str(self._registry_path), registry)

    def list_clients(self) -> list[dict[str, Any]]:
        registry = self._load()
        clients = registry.get("clients") or {}
        out: list[dict[str, Any]] = []
        for client_id, entry in clients.items():
            if not isinstance(entry, dict):
                continue
            cid = safe_client_id(str(client_id))
            sanitized = sanitize_registry_client(entry)
            out.append(
                {
                    "client_id": cid,
                    "display_name": sanitized.get("display_name"),
                    "widget_keys": sanitized.get("widget_keys") or [],
                    "has_config": (self._clients_root / cid / "config").is_dir(),
                    "config_revision": 0,
                }
            )
        return sorted(out, key=lambda item: item["client_id"])

    def get_client(self, client_id: str) -> dict[str, Any]:
        cid = safe_client_id(client_id)
        registry = self._load()
        entry = (registry.get("clients") or {}).get(cid)
        if not isinstance(entry, dict):
            raise ValueError(f"Client not found: {cid}")
        sanitized = sanitize_registry_client(entry)
        return {
            "client_id": cid,
            "display_name": sanitized.get("display_name"),
            "widget_keys": sanitized.get("widget_keys") or [],
            "has_config": (self._clients_root / cid / "config").is_dir(),
            "config_revision": 0,
        }

    def client_exists(self, client_id: str) -> bool:
        cid = safe_client_id(client_id)
        return cid in (self._load().get("clients") or {})

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
        registry = self._load()
        clients = registry.setdefault("clients", {})
        if cid in clients:
            raise ValueError(f"Client already exists: {cid}")
        full_key, prefix, _ = generate_widget_key()
        clients[cid] = {
            "display_name": display_name,
            "widget_keys": [
                build_registry_key_entry(
                    client_id=cid,
                    full_key=full_key,
                    allowed_origins=allowed_origins or [],
                )
            ],
            "integration_secrets": [],
        }
        self._save(registry)
        return CreateClientResult(
            client_id=cid,
            display_name=display_name,
            domain_pack=safe_client_id(domain_pack),
            widget_key_prefix=prefix,
            allowed_origins=list(allowed_origins or []),
            widget_key=full_key if reveal_widget_key else None,
        )

    def list_widget_keys(self, client_id: str) -> list[dict[str, Any]]:
        entry = self.get_client(client_id)
        return [sanitize_widget_key_entry(k) for k in entry.get("widget_keys") or []]

    def rotate_widget_key(
        self,
        client_id: str,
        *,
        allowed_origins: list[str] | None = None,
        revoke_key_id: str | None = None,
    ):
        raise NotImplementedError("Widget key rotation is only supported in firebase control plane.")

    def revoke_widget_key(self, client_id: str, key_id: str) -> None:
        raise NotImplementedError("Widget key revoke is only supported in firebase control plane.")

    def find_active_keys_by_prefix(self, prefix: str) -> list:
        from packages.core.admin.widget_keys import widget_key_matches
        from packages.core.control_plane.models import WidgetKeyRecord
        from datetime import datetime, timezone

        registry = self._load()
        out = []
        for client_id, entry in (registry.get("clients") or {}).items():
            if not isinstance(entry, dict):
                continue
            for key_entry in entry.get("widget_keys") or []:
                if not isinstance(key_entry, dict):
                    continue
                stored_prefix = str(key_entry.get("key_prefix") or "")[:12]
                if stored_prefix != prefix[:12]:
                    continue
                if key_entry.get("status") == "revoked":
                    continue
                out.append(
                    WidgetKeyRecord(
                        key_id=str(key_entry.get("key_id")),
                        client_id=str(client_id),
                        key_prefix=stored_prefix,
                        key_hash=str(key_entry.get("public_key_hash") or key_entry.get("key_hash") or ""),
                        hash_alg="local-dev",
                        allowed_origins=list(key_entry.get("allowed_origins") or []),
                        status="active",
                        created_at=datetime.now(timezone.utc),
                    )
                )
        return out

    def increment_config_revision(self, client_id: str) -> int:
        return 0

    def get_config_revision(self, client_id: str) -> int:
        return 0

    def save_registry_entry(self, client_id: str, entry: dict[str, Any]) -> None:
        registry = self._load()
        registry.setdefault("clients", {})[safe_client_id(client_id)] = entry
        self._save(registry)
