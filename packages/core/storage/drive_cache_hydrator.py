from __future__ import annotations

import logging
from pathlib import Path

from packages.adapters.storage.gcs_file_store import GcsFileStore
from packages.core.drive_sources.config import load_drive_sources
from packages.core.drive_sources.manifest import load_drive_sync_manifest
from packages.core.drive_sources.models import DriveFileRecord
from packages.core.drive_sources.paths import (
    drive_cache_files_prefix,
    drive_sync_manifest_key,
    drive_sync_manifest_path,
)
from packages.core.ports.file_store import FileStore
from packages.core.tenant.paths import client_config_dir, safe_client_id

logger = logging.getLogger(__name__)

INDEXABLE_DRIVE_FILE_STATUSES = frozenset({"synced", "skipped_unchanged", "fetched"})


def drive_file_indexable(file: DriveFileRecord) -> bool:
    return (
        file.status in INDEXABLE_DRIVE_FILE_STATUSES
        and bool(file.cache_file)
        and file.char_count > 0
    )


def _drive_cache_ready(clients_root: Path, client_id: str) -> bool:
    return drive_sync_manifest_path(clients_root, client_id).is_file()


def collect_drive_cache_keys(
    file_store: GcsFileStore,
    client_id: str,
    *,
    clients_root: Path | None = None,
) -> list[str]:
    cid = safe_client_id(client_id)
    root = clients_root or file_store.get_local_clients_root()
    keys: set[str] = {drive_sync_manifest_key()}

    manifest_path = drive_sync_manifest_path(root, cid)
    if not manifest_path.is_file():
        try:
            file_store.read_bytes(cid, drive_sync_manifest_key())
        except FileNotFoundError:
            return sorted(keys)

    manifest = load_drive_sync_manifest(root, cid)
    drive_config = load_drive_sources(client_config_dir(root, cid))
    enabled_sources = {source.id for source in drive_config.sources if source.enabled}

    for source_id, record in manifest.sources.items():
        if enabled_sources and source_id not in enabled_sources:
            continue
        for file in record.files.values():
            if not file.cache_file:
                continue
            if enabled_sources and not drive_file_indexable(file):
                continue
            if not enabled_sources and file.status not in INDEXABLE_DRIVE_FILE_STATUSES:
                continue
            keys.add(f"{drive_cache_files_prefix()}/{source_id}/{file.cache_file}")

    return sorted(keys)


def hydrate_client_drive_cache(
    *,
    client_id: str,
    file_store: FileStore,
    force: bool = False,
) -> int:
    """Download drive sync manifest and indexable cache files from GCS into the local cache."""
    if not isinstance(file_store, GcsFileStore):
        return 0

    cid = safe_client_id(client_id)
    clients_root = file_store.get_local_clients_root()
    if not force and _drive_cache_ready(clients_root, cid):
        manifest = load_drive_sync_manifest(clients_root, cid)
        if not manifest.sources:
            pass
        else:
            keys = collect_drive_cache_keys(file_store, cid, clients_root=clients_root)
            if len(keys) <= 1:
                return 0
            missing = [
                key
                for key in keys
                if key != drive_sync_manifest_key()
                and not (clients_root / cid / key).is_file()
            ]
            if not missing:
                return 0

    keys = collect_drive_cache_keys(file_store, cid, clients_root=clients_root)
    hydrated = 0
    for storage_key in keys:
        try:
            file_store.read_bytes(cid, storage_key)
            hydrated += 1
        except FileNotFoundError:
            logger.warning("Drive cache blob missing in GCS for client=%s key=%s", cid, storage_key)
    if hydrated:
        logger.info("Hydrated %s drive cache blob(s) for client=%s", hydrated, cid)
    return hydrated


def ensure_firebase_ingest_assets_hydrated(*, client_id: str) -> int:
    """Hydrate config, drive cache, and active index state for ingest jobs on firebase/GCS."""
    import os

    if os.getenv("STACK_PROFILE", "local").strip() != "firebase":
        return 0
    from packages.core.stack.factory import build_stack
    from packages.core.storage.tenant_cache_hydrator import (
        hydrate_client_config,
        hydrate_client_index_state,
    )

    stack = build_stack()
    if not isinstance(stack.file_store, GcsFileStore):
        return 0
    config_count = hydrate_client_config(
        client_id=client_id,
        file_store=stack.file_store,
        config_meta_store=stack.config_meta_store,
    )
    drive_count = hydrate_client_drive_cache(client_id=client_id, file_store=stack.file_store)
    index_count = hydrate_client_index_state(
        client_id=client_id,
        file_store=stack.file_store,
        include_active=True,
        include_previous=False,
    )
    return config_count + drive_count + index_count
