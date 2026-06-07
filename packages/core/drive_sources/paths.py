from __future__ import annotations

from pathlib import Path

from packages.core.tenant.paths import client_root, safe_client_id


def client_drive_cache_dir(clients_root: Path, client_id: str) -> Path:
    return client_root(clients_root, safe_client_id(client_id)) / "drive_cache"


def drive_cache_files_dir(clients_root: Path, client_id: str) -> Path:
    return client_drive_cache_dir(clients_root, client_id) / "files"


def drive_sync_manifest_path(clients_root: Path, client_id: str) -> Path:
    return client_drive_cache_dir(clients_root, client_id) / "drive_sync_manifest.json"


def drive_sync_manifest_key() -> str:
    return "drive_cache/drive_sync_manifest.json"


def drive_cache_files_prefix() -> str:
    return "drive_cache/files"



def drive_sources_config_path(config_dir: Path) -> Path:
    return config_dir / "drive_sources.yaml"
