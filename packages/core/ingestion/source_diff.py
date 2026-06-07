from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from packages.core.ingestion.manifest import read_active_manifest
from packages.core.ingestion.paths import (
    active_manifest_path,
    knowledge_index_path,
    source_manifest_path,
    vector_index_path,
)


@dataclass
class ActiveVersionSnapshot:
    version_id: str | None = None
    sources_by_path: dict[str, dict] = field(default_factory=dict)
    chunks_by_source_id: dict[str, list[dict]] = field(default_factory=dict)
    vectors_by_chunk_id: dict[str, list[float]] = field(default_factory=dict)
    embedding_model: str | None = None
    embedding_dims: int | None = None


def load_active_snapshot(clients_root: Path, client_id: str) -> ActiveVersionSnapshot | None:
    manifest = read_active_manifest(active_manifest_path(clients_root, client_id))
    if not manifest.active:
        return None

    version_id = manifest.active
    source_path = source_manifest_path(clients_root, client_id, version_id)
    knowledge_path = knowledge_index_path(clients_root, client_id, version_id)
    vector_path = vector_index_path(clients_root, client_id, version_id)

    if not source_path.is_file() or not knowledge_path.is_file():
        return None

    snapshot = ActiveVersionSnapshot(version_id=version_id)
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    for source in source_payload.get("sources", []):
        if isinstance(source, dict) and source.get("path"):
            snapshot.sources_by_path[str(source["path"])] = source

    knowledge_payload = json.loads(knowledge_path.read_text(encoding="utf-8"))
    for chunk in knowledge_payload.get("chunks", []):
        if not isinstance(chunk, dict):
            continue
        source_id = str(chunk.get("source_id", ""))
        snapshot.chunks_by_source_id.setdefault(source_id, []).append(chunk)

    if vector_path.is_file():
        vector_payload = json.loads(vector_path.read_text(encoding="utf-8"))
        snapshot.embedding_model = vector_payload.get("embedding_model")
        snapshot.embedding_dims = vector_payload.get("embedding_dims")
        for item in vector_payload.get("vectors", []):
            if not isinstance(item, dict):
                continue
            chunk_id = str(item.get("chunk_id", ""))
            embedding = item.get("embedding")
            if chunk_id and isinstance(embedding, list):
                snapshot.vectors_by_chunk_id[chunk_id] = [float(v) for v in embedding]

    return snapshot


def find_unchanged_source(
    snapshot: ActiveVersionSnapshot | None,
    *,
    internal_path: str,
    content_hash: str,
) -> dict | None:
    if snapshot is None:
        return None
    prior = snapshot.sources_by_path.get(internal_path)
    if not prior:
        return None
    if prior.get("content_hash") != content_hash:
        return None
    if prior.get("status") not in ("indexed", "skipped_unchanged"):
        return None
    return prior
