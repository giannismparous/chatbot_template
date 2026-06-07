from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from packages.core.ingestion.models import (
    ActiveManifest,
    IngestReport,
    KnowledgeChunk,
    SourceRecord,
    utc_now_iso,
)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def read_active_manifest(path: Path) -> ActiveManifest:
    if not path.is_file():
        return ActiveManifest()
    return ActiveManifest.from_dict(read_json(path))


def write_active_manifest(path: Path, manifest: ActiveManifest) -> None:
    write_json_atomic(path, manifest.to_dict())


def set_pending_version(manifest_path: Path, version_id: str) -> ActiveManifest:
    manifest = read_active_manifest(manifest_path)
    manifest.pending = version_id
    write_active_manifest(manifest_path, manifest)
    return manifest


def activate_pending_version(manifest_path: Path) -> ActiveManifest:
    manifest = read_active_manifest(manifest_path)
    if not manifest.pending:
        raise ValueError("No pending version to activate")
    manifest.previous = manifest.active
    manifest.active = manifest.pending
    manifest.pending = None
    write_active_manifest(manifest_path, manifest)
    return manifest


def write_knowledge_index(
    path: Path,
    *,
    client_id: str,
    version_id: str,
    chunks: list[KnowledgeChunk],
) -> None:
    write_json_atomic(
        path,
        {
            "client_id": client_id,
            "version_id": version_id,
            "created_at": utc_now_iso(),
            "chunks": [c.to_dict() for c in chunks],
        },
    )


def write_source_manifest(
    path: Path,
    *,
    client_id: str,
    version_id: str,
    sources: list[SourceRecord],
) -> None:
    write_json_atomic(
        path,
        {
            "client_id": client_id,
            "version_id": version_id,
            "created_at": utc_now_iso(),
            "sources": [s.to_dict() for s in sources],
        },
    )


def write_vector_index(
    path: Path,
    *,
    client_id: str,
    version_id: str,
    embedding_model: str,
    embedding_dims: int,
    vectors: list[dict[str, Any]],
) -> None:
    write_json_atomic(
        path,
        {
            "client_id": client_id,
            "version_id": version_id,
            "embedding_model": embedding_model,
            "embedding_dims": embedding_dims,
            "created_at": utc_now_iso(),
            "vectors": vectors,
        },
    )


def write_ingest_report(path: Path, report: IngestReport) -> None:
    write_json_atomic(path, report.to_dict())


def read_active_manifest_storage(storage, client_id: str) -> ActiveManifest:
    from packages.core.ingestion.paths import active_manifest_key

    key = active_manifest_key()
    if not storage.exists(client_id, key):
        return ActiveManifest()
    return ActiveManifest.from_dict(storage.read_json(client_id, key))


def write_active_manifest_storage(storage, client_id: str, manifest: ActiveManifest) -> None:
    from packages.core.ingestion.paths import active_manifest_key

    storage.write_json_atomic(client_id, active_manifest_key(), manifest.to_dict())


def set_pending_version_storage(storage, client_id: str, version_id: str) -> ActiveManifest:
    manifest = read_active_manifest_storage(storage, client_id)
    manifest.pending = version_id
    write_active_manifest_storage(storage, client_id, manifest)
    return manifest


def activate_pending_version_storage(storage, client_id: str) -> ActiveManifest:
    manifest = read_active_manifest_storage(storage, client_id)
    if not manifest.pending:
        raise ValueError("No pending version to activate")
    manifest.previous = manifest.active
    manifest.active = manifest.pending
    manifest.pending = None
    write_active_manifest_storage(storage, client_id, manifest)
    storage.remember_active_index_version(client_id, manifest.active or "")
    return manifest


def write_knowledge_index_storage(
    storage,
    client_id: str,
    *,
    version_id: str,
    chunks: list[KnowledgeChunk],
) -> None:
    from packages.core.ingestion.paths import knowledge_index_key

    storage.write_json_atomic(
        client_id,
        knowledge_index_key(version_id),
        {
            "client_id": client_id,
            "version_id": version_id,
            "created_at": utc_now_iso(),
            "chunks": [c.to_dict() for c in chunks],
        },
    )


def write_source_manifest_storage(
    storage,
    client_id: str,
    *,
    version_id: str,
    sources: list[SourceRecord],
) -> None:
    from packages.core.ingestion.paths import source_manifest_key

    storage.write_json_atomic(
        client_id,
        source_manifest_key(version_id),
        {
            "client_id": client_id,
            "version_id": version_id,
            "created_at": utc_now_iso(),
            "sources": [s.to_dict() for s in sources],
        },
    )


def write_vector_index_storage(
    storage,
    client_id: str,
    *,
    version_id: str,
    embedding_model: str,
    embedding_dims: int,
    vectors: list[dict[str, Any]],
) -> None:
    from packages.core.ingestion.paths import vector_index_key

    storage.write_json_atomic(
        client_id,
        vector_index_key(version_id),
        {
            "client_id": client_id,
            "version_id": version_id,
            "embedding_model": embedding_model,
            "embedding_dims": embedding_dims,
            "created_at": utc_now_iso(),
            "vectors": vectors,
        },
    )


def write_ingest_report_storage(storage, client_id: str, version_id: str, report: IngestReport) -> None:
    from packages.core.ingestion.paths import ingest_report_key

    storage.write_json_atomic(client_id, ingest_report_key(version_id), report.to_dict())


def rollback_active_version_storage(storage, client_id: str) -> ActiveManifest:
    manifest = read_active_manifest_storage(storage, client_id)
    if not manifest.previous:
        raise ValueError("No previous version to roll back to")
    manifest.active = manifest.previous
    manifest.previous = None
    write_active_manifest_storage(storage, client_id, manifest)
    return manifest


def rollback_active_version(manifest_path: Path) -> ActiveManifest:
    manifest = read_active_manifest(manifest_path)
    if not manifest.previous:
        raise ValueError("No previous version to roll back to")
    manifest.active = manifest.previous
    manifest.previous = None
    write_active_manifest(manifest_path, manifest)
    return manifest
