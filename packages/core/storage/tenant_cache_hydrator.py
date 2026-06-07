from __future__ import annotations

import logging
from pathlib import Path

from packages.adapters.storage.gcs_file_store import GcsFileStore
from packages.core.config.loader import CONFIG_FILES, FAQ_FILENAME
from packages.core.ports.config_meta_store import ConfigMetaStore
from packages.core.ports.file_store import FileStore
from packages.core.tenant.paths import client_config_dir, safe_client_id

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_KEYS = (
    "config/client.yaml",
    *(f"config/{name}" for name in CONFIG_FILES.values() if name != "client.yaml"),
    f"config/{FAQ_FILENAME}",
)


def _config_dir_ready(clients_root: Path, client_id: str) -> bool:
    config_dir = client_config_dir(clients_root, client_id)
    return config_dir.is_dir() and (config_dir / "client.yaml").is_file()


def _collect_config_keys(
    client_id: str,
    *,
    file_store: GcsFileStore,
    config_meta_store: ConfigMetaStore | None,
) -> list[str]:
    keys: set[str] = set()
    if config_meta_store is not None:
        for meta in config_meta_store.list_meta(client_id):
            storage_key = str(meta.storage_key or "").strip()
            if storage_key.startswith("config/"):
                keys.add(storage_key)
        if keys:
            return sorted(keys)

    for obj in file_store.list_prefix(client_id, "config/"):
        if obj.key.startswith("config/"):
            keys.add(obj.key)
    if keys:
        return sorted(keys)

    return list(DEFAULT_CONFIG_KEYS)


def hydrate_client_config(
    *,
    client_id: str,
    file_store: FileStore,
    config_meta_store: ConfigMetaStore | None = None,
    force: bool = False,
) -> int:
    """Download tenant config blobs from GCS into the local tenant cache."""
    if not isinstance(file_store, GcsFileStore):
        return 0

    cid = safe_client_id(client_id)
    clients_root = file_store.get_local_clients_root()
    if not force and _config_dir_ready(clients_root, cid):
        return 0

    keys = _collect_config_keys(cid, file_store=file_store, config_meta_store=config_meta_store)
    if "config/client.yaml" not in keys:
        keys.insert(0, "config/client.yaml")

    hydrated = 0
    for storage_key in keys:
        if not storage_key.startswith("config/"):
            continue
        try:
            file_store.read_bytes(cid, storage_key)
            hydrated += 1
        except FileNotFoundError:
            logger.warning("Config blob missing in GCS for client=%s key=%s", cid, storage_key)
    return hydrated


def hydrate_startup_tenant_configs(
    *,
    file_store: FileStore,
    config_meta_store: ConfigMetaStore | None,
    client_ids: list[str],
) -> None:
    if not isinstance(file_store, GcsFileStore):
        return
    for client_id in client_ids:
        count = hydrate_client_config(
            client_id=client_id,
            file_store=file_store,
            config_meta_store=config_meta_store,
        )
        if count:
            logger.info("Hydrated %s config file(s) for client=%s", count, client_id)
