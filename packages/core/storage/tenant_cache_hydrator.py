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

EVAL_SUITE_KEY = "tests/eval_suite.yaml"


def _config_dir_ready(clients_root: Path, client_id: str) -> bool:
    config_dir = client_config_dir(clients_root, client_id)
    return config_dir.is_dir() and (config_dir / "client.yaml").is_file()


def _eval_assets_ready(clients_root: Path, client_id: str) -> bool:
    tests_root = clients_root / safe_client_id(client_id) / "tests"
    return (tests_root / "eval_suite.yaml").is_file() and (tests_root / "cases").is_dir()


def _should_hydrate_test_key(relative_key: str) -> bool:
    if not relative_key.startswith("tests/"):
        return False
    rel = relative_key[len("tests/") :]
    if rel.startswith("output/") or rel == "output":
        return False
    if rel == "eval_suite.yaml":
        return True
    if rel.startswith("cases/"):
        return True
    if rel.startswith("fixtures/"):
        return True
    return False


def _collect_eval_test_keys(file_store: GcsFileStore, client_id: str) -> list[str]:
    keys: set[str] = set()
    for obj in file_store.list_prefix(client_id, "tests/"):
        if _should_hydrate_test_key(obj.key):
            keys.add(obj.key)
    keys.add(EVAL_SUITE_KEY)
    return sorted(keys)


def _download_keys(file_store: GcsFileStore, client_id: str, keys: list[str]) -> int:
    hydrated = 0
    for storage_key in keys:
        try:
            file_store.read_bytes(client_id, storage_key)
            hydrated += 1
        except FileNotFoundError:
            logger.warning("Blob missing in GCS for client=%s key=%s", client_id, storage_key)
    return hydrated


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
    return _download_keys(file_store, cid, keys)


def hydrate_client_eval_assets(
    *,
    client_id: str,
    file_store: FileStore,
    force: bool = False,
) -> int:
    """Download eval suite + case files from GCS into the local tenant cache (not tests/output)."""
    if not isinstance(file_store, GcsFileStore):
        return 0

    cid = safe_client_id(client_id)
    clients_root = file_store.get_local_clients_root()
    if not force and _eval_assets_ready(clients_root, cid):
        return 0

    keys = _collect_eval_test_keys(file_store, cid)
    return _download_keys(file_store, cid, keys)


def ensure_firebase_eval_assets_hydrated(*, client_id: str) -> int:
    """Hydrate eval assets when running on firebase/GCS (no-op for local profile)."""
    import os

    if os.getenv("STACK_PROFILE", "local").strip() != "firebase":
        return 0
    from packages.core.stack.factory import build_stack

    stack = build_stack()
    if not isinstance(stack.file_store, GcsFileStore):
        return 0
    config_count = hydrate_client_config(
        client_id=client_id,
        file_store=stack.file_store,
        config_meta_store=stack.config_meta_store,
    )
    eval_count = hydrate_client_eval_assets(client_id=client_id, file_store=stack.file_store)
    return config_count + eval_count


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
