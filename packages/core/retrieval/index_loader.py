from __future__ import annotations

import json
from pathlib import Path

from packages.core.ingestion.manifest import read_active_manifest
from packages.core.ingestion.paths import (
    active_manifest_path,
    knowledge_index_path,
    vector_index_path,
)
from packages.core.retrieval.models import IndexedChunk, TenantIndex


def _chunk_from_dict(raw: dict) -> IndexedChunk | None:
    if not isinstance(raw, dict):
        return None
    content = str(raw.get("content", ""))
    if not content and not raw.get("title"):
        return None
    status = raw.get("embedding_status")
    if status == "failed":
        return None
    return IndexedChunk(
        id=str(raw.get("id", "")),
        source_id=str(raw.get("source_id", "")),
        title=str(raw.get("title", "")),
        content=content,
        internal_url=str(raw.get("internal_url") or raw.get("url") or "local_file"),
        citation_url=raw.get("citation_url"),
        source_visibility=str(raw.get("source_visibility", "internal")),
        language=str(raw.get("language", "unknown")),
        embedding_status=status,
    )


def _load_knowledge_payload(path: Path) -> list[IndexedChunk]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_items: list[dict] = []
    if isinstance(payload, list):
        raw_items = [x for x in payload if isinstance(x, dict)]
    elif isinstance(payload, dict):
        raw_items = [x for x in (payload.get("chunks") or payload.get("documents") or []) if isinstance(x, dict)]
    chunks: list[IndexedChunk] = []
    for raw in raw_items:
        if "internal_url" not in raw and raw.get("url"):
            raw = dict(raw)
            raw["internal_url"] = raw.get("url")
        chunk = _chunk_from_dict(raw)
        if chunk and chunk.id:
            chunks.append(chunk)
    return chunks


def _load_vectors(path: Path) -> tuple[dict[str, list[float]], str | None, int | None]:
    if not path.is_file():
        return {}, None, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}, None, None
    vectors: dict[str, list[float]] = {}
    for item in payload.get("vectors") or []:
        if not isinstance(item, dict):
            continue
        chunk_id = str(item.get("chunk_id", ""))
        embedding = item.get("embedding")
        if chunk_id and isinstance(embedding, list):
            vectors[chunk_id] = [float(v) for v in embedding]
    model = payload.get("embedding_model")
    dims = payload.get("embedding_dims")
    return vectors, (str(model) if model else None), (int(dims) if dims else None)


def load_tenant_index(
    *,
    clients_root: Path,
    client_id: str,
    legacy_fallback_path: Path,
) -> TenantIndex:
    manifest_path = active_manifest_path(clients_root, client_id)
    manifest = read_active_manifest(manifest_path)
    if manifest.active:
        version_id = manifest.active
        knowledge_path = knowledge_index_path(clients_root, client_id, version_id)
        if knowledge_path.is_file():
            chunks = _load_knowledge_payload(knowledge_path)
            vector_path = vector_index_path(clients_root, client_id, version_id)
            vectors, model, dims = _load_vectors(vector_path)
            return TenantIndex(
                client_id=client_id,
                version_id=version_id,
                chunks=chunks,
                vectors_by_chunk_id=vectors,
                embedding_model=model,
                embedding_dims=dims,
                is_legacy=False,
            )

    legacy_chunks = _load_knowledge_payload(legacy_fallback_path)
    return TenantIndex(
        client_id=client_id,
        version_id=None,
        chunks=legacy_chunks,
        vectors_by_chunk_id={},
        embedding_model=None,
        embedding_dims=None,
        is_legacy=True,
    )
