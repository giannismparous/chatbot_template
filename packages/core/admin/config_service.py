from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packages.config.loaders import load_yaml, save_yaml
from packages.core.admin.config_keys import config_filename, resolve_config_key
from packages.core.config.loader import TenantConfigLoader
from packages.core.config.models import ConfigValidationError
from packages.core.control_plane.models import ConfigMetaRecord
from packages.core.llm.validation import validate_llm_config
from packages.core.ports.client_registry import ClientRegistryStore
from packages.core.ports.config_meta_store import ConfigMetaStore
from packages.core.privacy.config import validate_privacy_config
from packages.core.safety.config import validate_safety_config
from packages.core.stack.factory import project_root
from packages.core.storage.tenant_storage import TenantStorage
from packages.core.tenant.paths import client_config_dir, safe_client_id


class ConfigService:
    def __init__(
        self,
        *,
        clients_root: Path,
        tenant_storage: TenantStorage | None = None,
        config_meta_store: ConfigMetaStore | None = None,
        registry_store: ClientRegistryStore | None = None,
    ) -> None:
        self._clients_root = clients_root.resolve()
        self._packs_root = project_root() / "packages" / "domain_packs"
        self._tenant_storage = tenant_storage
        self._config_meta_store = config_meta_store
        self._registry_store = registry_store

    def _loader(self) -> TenantConfigLoader:
        return TenantConfigLoader(clients_root=self._clients_root, domain_packs_root=self._packs_root)

    def _storage_key(self, filename: str) -> str:
        return f"config/{filename}"

    def _content_type(self, filename: str) -> str:
        if filename.endswith(".json"):
            return "application/json"
        return "application/x-yaml"

    def _write_config_blob(self, client_id: str, filename: str, text: str) -> None:
        cid = safe_client_id(client_id)
        key = self._storage_key(filename)
        if self._tenant_storage is not None:
            self._tenant_storage.write_text(
                cid,
                key,
                text,
                content_type=self._content_type(filename),
            )
        else:
            path = client_config_dir(self._clients_root, cid) / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def _record_config_meta(self, client_id: str, config_key: str, filename: str, text: str) -> None:
        if self._config_meta_store is None or self._registry_store is None:
            return
        cid = safe_client_id(client_id)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        existing = self._config_meta_store.get_meta(cid, config_key)
        revision = (existing.revision + 1) if existing else 1
        record = ConfigMetaRecord(
            client_id=cid,
            config_key=config_key,
            storage_key=self._storage_key(filename),
            content_sha256=digest,
            size_bytes=len(text.encode("utf-8")),
            content_type=self._content_type(filename),
            revision=revision,
            updated_at=datetime.now(timezone.utc),
        )
        self._config_meta_store.put_meta(record)
        self._registry_store.increment_config_revision(cid)

    def get_config(self, client_id: str, config_key: str) -> dict[str, Any]:
        cid = safe_client_id(client_id)
        canonical = resolve_config_key(config_key)
        config_dir = client_config_dir(self._clients_root, cid)
        if not config_dir.is_dir():
            raise FileNotFoundError(f"Client config not found: {cid}")
        filename = config_filename(canonical)
        key = self._storage_key(filename)
        if self._tenant_storage is not None and self._tenant_storage.exists(cid, key):
            if filename.endswith(".json"):
                data = self._tenant_storage.read_json(cid, key)
                return data if isinstance(data, dict) else {}
            return load_yaml_from_text(self._tenant_storage.read_text(cid, key))
        path = config_dir / filename
        if filename.endswith(".json"):
            if not path.is_file():
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        return load_yaml(str(path))

    def put_config(self, client_id: str, config_key: str, payload: dict[str, Any]) -> None:
        cid = safe_client_id(client_id)
        canonical = resolve_config_key(config_key)
        config_dir = client_config_dir(self._clients_root, cid)
        if not config_dir.is_dir():
            raise FileNotFoundError(f"Client config not found: {cid}")
        if not isinstance(payload, dict):
            raise ConfigValidationError("Config payload must be an object.")

        filename = config_filename(canonical)
        path = config_dir / filename
        backup: str | None = path.read_text(encoding="utf-8") if path.is_file() else None

        try:
            loader = self._loader()
            merged = loader.load(cid)

            if canonical == "source_mapping":
                from packages.core.ingestion.source_mapping import (
                    SourceMappingValidationError,
                    save_source_mapping,
                    validate_source_mapping_document,
                )

                try:
                    config = validate_source_mapping_document(payload, whitelist=merged.source_whitelist)
                except SourceMappingValidationError as exc:
                    raise ConfigValidationError(str(exc)) from exc
                save_source_mapping(config_dir, config)
                if self._tenant_storage is not None:
                    text = (config_dir / "source_mapping.yaml").read_text(encoding="utf-8")
                    self._write_config_blob(cid, "source_mapping.yaml", text)
                    self._record_config_meta(cid, canonical, "source_mapping.yaml", text)
            elif filename.endswith(".json"):
                text = json.dumps(payload, indent=2) + "\n"
                path.write_text(text, encoding="utf-8")
                self._write_config_blob(cid, filename, text)
                self._record_config_meta(cid, canonical, filename, text)
            else:
                save_yaml(str(path), payload)
                text = path.read_text(encoding="utf-8")
                self._write_config_blob(cid, filename, text)
                self._record_config_meta(cid, canonical, filename, text)

            loader.clear_cache(cid)
            merged = loader.load(cid)

            if canonical == "privacy":
                validate_privacy_config(merged)
            elif canonical in {"guardrails", "crisis_rules"}:
                validate_safety_config(merged)
            elif canonical == "llm":
                validate_llm_config(merged)
        except Exception:
            if backup is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(backup, encoding="utf-8")
            loader = self._loader()
            loader.clear_cache(cid)
            raise


def load_yaml_from_text(text: str) -> dict[str, Any]:
    import tempfile

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".yaml") as tmp:
        tmp.write(text)
        tmp_path = tmp.name
    try:
        data = load_yaml(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return data if isinstance(data, dict) else {}
