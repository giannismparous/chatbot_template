from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from packages.config.loaders import load_yaml
from packages.core.ports.config_store import ConfigStore
from packages.core.ports.file_store import FileStore
from packages.core.tenant.paths import client_config_dir, safe_client_id

PLATFORM_REGISTRY_KEY = "platform/registry.yaml"


class YamlConfigStore(ConfigStore):
    def __init__(
        self,
        clients_root: Path,
        registry_path: Path,
        *,
        file_store: FileStore | None = None,
        profile: str = "local",
    ) -> None:
        self._clients_root = clients_root.resolve()
        self._registry_path = registry_path.resolve()
        self._file_store = file_store
        self._profile = profile

    def get_clients_root(self) -> Path:
        if self._file_store is not None:
            return self._file_store.get_local_clients_root()
        return self._clients_root

    def get_registry_path(self) -> Path:
        return self._registry_path

    def load_registry(self) -> dict[str, Any]:
        if self._profile == "firebase" and self._file_store is not None:
            return self._load_registry_from_gcs()
        if not self._registry_path.is_file():
            raise FileNotFoundError(f"Client registry not found: {self._registry_path}")
        data = load_yaml(str(self._registry_path))
        return data if isinstance(data, dict) else {}

    def _load_registry_from_gcs(self) -> dict[str, Any]:
        from packages.adapters.storage.gcs_file_store import GcsFileStore

        if not isinstance(self._file_store, GcsFileStore):
            if not self._registry_path.is_file():
                raise FileNotFoundError(f"Client registry not found: {self._registry_path}")
            data = load_yaml(str(self._registry_path))
            return data if isinstance(data, dict) else {}
        blob = self._file_store._bucket().blob(PLATFORM_REGISTRY_KEY)
        if not blob.exists():
            raise FileNotFoundError(
                f"Platform registry not found in GCS: gs://{self._file_store.bucket_name}/{PLATFORM_REGISTRY_KEY}. "
                "Upload platform/registry.yaml during migration. "
                "NOTE: plaintext widget keys are staging-only until Phase 20 hashed storage."
            )
        text = blob.download_as_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".yaml") as tmp:
            tmp.write(text)
            tmp_path = tmp.name
        try:
            data = load_yaml(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        return data if isinstance(data, dict) else {}

    def get_client_config_dir(self, client_id: str) -> Path:
        return client_config_dir(self.get_clients_root(), client_id)


def build_yaml_config_store(
    project_root: Path,
    stack_paths: dict[str, Any],
    *,
    file_store: FileStore | None = None,
    profile: str = "local",
) -> YamlConfigStore:
    paths = stack_paths.get("paths") or {}
    clients_root = Path(
        os.getenv("CLIENTS_ROOT", paths.get("clients_root", "data/clients"))
    )
    if not clients_root.is_absolute():
        clients_root = project_root / clients_root

    registry = os.getenv(
        "CLIENT_REGISTRY_PATH",
        paths.get("registry", "packages/config/clients/registry.yaml"),
    )
    registry_path = Path(registry)
    if not registry_path.is_absolute():
        registry_path = project_root / registry_path

    if profile == "firebase" and file_store is not None:
        clients_root = file_store.get_local_clients_root()

    return YamlConfigStore(
        clients_root=clients_root,
        registry_path=registry_path,
        file_store=file_store,
        profile=profile,
    )

