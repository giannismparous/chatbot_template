from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from packages.adapters.storage.gcs_file_store import GcsFileStore
from packages.core.ingestion.manifest import read_active_manifest
from packages.core.ingestion.paths import (
    active_manifest_key,
    active_manifest_path,
    ingest_report_key,
    knowledge_index_key,
    knowledge_index_path,
    source_manifest_key,
    vector_index_key,
)
from packages.core.ports.file_store import FileStore
from packages.core.storage.keys import gcs_object_name
from packages.core.ingestion.paths import client_indexes_dir
from packages.core.tenant.paths import safe_client_id

logger = logging.getLogger(__name__)


@dataclass
class ActiveIndexRuntimeReport:
    client_id: str
    hydrated_blobs: int = 0
    tenant_cache_root: str = ""
    manifest_local_path: str = ""
    manifest_exists: bool = False
    active_version: str | None = None
    knowledge_index_local_path: str = ""
    knowledge_index_exists: bool = False
    source_count: int = 0
    chunk_count: int = 0
    gcs_manifest_key: str = ""
    gcs_knowledge_index_key: str | None = None
    skipped_reason: str | None = None

    def emit(self) -> None:
        for line in self.lines():
            print(line, flush=True)

    def lines(self) -> list[str]:
        return [
            f"[api-runtime] tenant_cache_root={self.tenant_cache_root}",
            f"[api-runtime] manifest_local_path={self.manifest_local_path}",
            f"[api-runtime] manifest_exists={self.manifest_exists}",
            f"[api-runtime] gcs_manifest_key={self.gcs_manifest_key}",
            f"[api-runtime] active_index_version={self.active_version or 'none'}",
            f"[api-runtime] knowledge_index_local_path={self.knowledge_index_local_path}",
            f"[api-runtime] knowledge_index_exists={self.knowledge_index_exists}",
            f"[api-runtime] gcs_knowledge_index_key={self.gcs_knowledge_index_key or 'n/a'}",
            f"[api-runtime] hydrated_index_blobs={self.hydrated_blobs}",
            f"[api-runtime] active_source_count={self.source_count}",
            f"[api-runtime] active_chunk_count={self.chunk_count}",
            *( [f"[api-runtime] skipped_reason={self.skipped_reason}"] if self.skipped_reason else [] ),
        ]


def _active_index_runtime_ready(clients_root: Path, client_id: str) -> bool:
    cid = safe_client_id(client_id)
    manifest_path = active_manifest_path(clients_root, cid)
    if not manifest_path.is_file():
        return False
    manifest = read_active_manifest(manifest_path)
    if not manifest.active:
        return False
    return knowledge_index_path(clients_root, cid, manifest.active).is_file()


def _pending_index_ready(clients_root: Path, client_id: str) -> bool:
    cid = safe_client_id(client_id)
    manifest_path = active_manifest_path(clients_root, cid)
    if not manifest_path.is_file():
        return False
    manifest = read_active_manifest(manifest_path)
    if not manifest.pending:
        return False
    return knowledge_index_path(clients_root, cid, manifest.pending).is_file()


def _clear_local_index_cache(clients_root: Path, client_id: str) -> None:
    index_root = client_indexes_dir(clients_root, client_id)
    if index_root.is_dir():
        import shutil

        shutil.rmtree(index_root, ignore_errors=True)


def _required_active_index_keys(version_id: str) -> list[str]:
    return [
        active_manifest_key(),
        knowledge_index_key(version_id),
        source_manifest_key(version_id),
        vector_index_key(version_id),
        ingest_report_key(version_id),
    ]


def _count_active_index_stats(clients_root: Path, client_id: str, version_id: str) -> tuple[int, int]:
    source_count = 0
    chunk_count = 0
    knowledge_path = knowledge_index_path(clients_root, client_id, version_id)
    if knowledge_path.is_file():
        payload = json.loads(knowledge_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            chunks = payload.get("chunks") or payload.get("documents") or []
            if isinstance(chunks, list):
                chunk_count = len(chunks)
    source_path = knowledge_path.parent / "source_manifest.json"
    if source_path.is_file():
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            sources = payload.get("sources") or []
            if isinstance(sources, list):
                source_count = len(sources)
    return source_count, chunk_count


def hydrate_client_active_index_for_runtime(
    *,
    client_id: str,
    file_store: FileStore,
    force: bool = False,
) -> ActiveIndexRuntimeReport:
    """Hydrate active index manifest + active version blobs for API/chat runtime."""
    cid = safe_client_id(client_id)
    report = ActiveIndexRuntimeReport(client_id=cid)

    if not isinstance(file_store, GcsFileStore):
        report.skipped_reason = "file_store_not_gcs"
        return report

    clients_root = file_store.get_local_clients_root()
    report.tenant_cache_root = str(clients_root)
    report.manifest_local_path = str(active_manifest_path(clients_root, cid))
    report.gcs_manifest_key = gcs_object_name(cid, active_manifest_key())

    if not force and _active_index_runtime_ready(clients_root, cid):
        manifest = read_active_manifest(active_manifest_path(clients_root, cid))
        report.manifest_exists = True
        report.active_version = manifest.active
        if manifest.active:
            report.knowledge_index_local_path = str(
                knowledge_index_path(clients_root, cid, manifest.active)
            )
            report.knowledge_index_exists = True
            report.gcs_knowledge_index_key = gcs_object_name(
                cid,
                knowledge_index_key(manifest.active),
            )
            report.source_count, report.chunk_count = _count_active_index_stats(
                clients_root,
                cid,
                manifest.active,
            )
        return report

    if force:
        _clear_local_index_cache(clients_root, cid)

    hydrated = 0
    try:
        file_store.read_bytes(cid, active_manifest_key())
        hydrated += 1
    except FileNotFoundError:
        logger.warning("Active manifest missing in GCS for client=%s", cid)
        report.skipped_reason = "manifest_missing_in_gcs"
        return report

    manifest = read_active_manifest(active_manifest_path(clients_root, cid))
    report.manifest_exists = True
    report.active_version = manifest.active
    if not manifest.active:
        report.skipped_reason = "no_active_version"
        report.hydrated_blobs = hydrated
        return report

    keys = _required_active_index_keys(manifest.active)
    prefix = f"indexes/versions/{manifest.active}/"
    for obj in file_store.list_prefix(cid, prefix):
        if obj.key.startswith(prefix):
            keys.append(obj.key)
    keys = sorted(set(keys))

    for storage_key in keys:
        try:
            file_store.read_bytes(cid, storage_key)
            hydrated += 1
        except FileNotFoundError:
            logger.warning(
                "Active index blob missing in GCS for client=%s key=%s",
                cid,
                storage_key,
            )

    report.hydrated_blobs = hydrated
    report.knowledge_index_local_path = str(
        knowledge_index_path(clients_root, cid, manifest.active)
    )
    report.knowledge_index_exists = knowledge_index_path(
        clients_root,
        cid,
        manifest.active,
    ).is_file()
    report.gcs_knowledge_index_key = gcs_object_name(
        cid,
        knowledge_index_key(manifest.active),
    )
    report.source_count, report.chunk_count = _count_active_index_stats(
        clients_root,
        cid,
        manifest.active,
    )
    return report


def prepare_firebase_api_runtime_index(*, client_id: str, stack) -> ActiveIndexRuntimeReport:
    from packages.core.storage.tenant_cache_hydrator import hydrate_client_config

    hydrate_client_config(
        client_id=client_id,
        file_store=stack.file_store,
        config_meta_store=stack.config_meta_store,
        force=False,
    )
    return hydrate_client_active_index_for_runtime(
        client_id=client_id,
        file_store=stack.file_store,
        force=True,
    )
