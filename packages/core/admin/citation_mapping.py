from __future__ import annotations

import json
from pathlib import Path

from packages.core.config.loader import TenantConfigLoader
from packages.core.ingestion.manifest import read_json
from packages.core.ingestion.paths import active_manifest_path, knowledge_index_path
from packages.core.ingestion.source_mapping import load_source_mapping
from packages.core.stack.factory import project_root
from packages.core.tenant.paths import client_config_dir, safe_client_id


def latest_index_created_at(clients_root: Path, client_id: str) -> str | None:
    cid = safe_client_id(client_id)
    manifest = read_json(active_manifest_path(clients_root, cid))
    version_id = manifest.get("pending") or manifest.get("active")
    if not version_id:
        return None
    index_path = knowledge_index_path(clients_root, cid, str(version_id))
    if not index_path.is_file():
        return None
    payload = read_json(index_path)
    created = payload.get("created_at")
    return str(created) if created else None


def mapping_requires_reingest(clients_root: Path, client_id: str) -> bool:
    cid = safe_client_id(client_id)
    config_dir = client_config_dir(clients_root, cid)
    mapping = load_source_mapping(config_dir)
    if not mapping.updated_at:
        return False
    index_created = latest_index_created_at(clients_root, cid)
    if not index_created:
        return bool(mapping.uploads)
    return mapping.updated_at > index_created


def load_client_whitelist(clients_root: Path, client_id: str) -> dict:
    loader = TenantConfigLoader(
        clients_root=clients_root,
        domain_packs_root=project_root() / "packages" / "domain_packs",
    )
    return loader.load(safe_client_id(client_id)).source_whitelist or {}
