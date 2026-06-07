from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from packages.adapters.embedding.gemini_embedding_adapter import model_slug
from packages.core.ingestion.manifest import write_json_atomic


def embedding_cache_dir(clients_root: Path, client_id: str) -> Path:
    from packages.core.ingestion.paths import client_indexes_dir

    return client_indexes_dir(clients_root, client_id) / "embedding_cache"


def cache_entry_path(
    clients_root: Path,
    client_id: str,
    *,
    content_hash: str,
    embedding_model: str,
) -> Path:
    return embedding_cache_dir(clients_root, client_id) / model_slug(embedding_model) / f"{content_hash}.json"


def read_cached_vector(
    clients_root: Path,
    client_id: str,
    *,
    content_hash: str,
    embedding_model: str,
) -> list[float] | None:
    path = cache_entry_path(
        clients_root,
        client_id,
        content_hash=content_hash,
        embedding_model=embedding_model,
    )
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        return None
    vector = payload.get("vector")
    if not isinstance(vector, list) or not vector:
        return None
    return [float(v) for v in vector]


def write_cached_vector(
    clients_root: Path,
    client_id: str,
    *,
    content_hash: str,
    embedding_model: str,
    vector: list[float],
    embedding_dims: int,
) -> None:
    path = cache_entry_path(
        clients_root,
        client_id,
        content_hash=content_hash,
        embedding_model=embedding_model,
    )
    payload: dict[str, Any] = {
        "content_hash": content_hash,
        "embedding_model": embedding_model,
        "embedding_dims": embedding_dims,
        "vector": vector,
    }
    write_json_atomic(path, payload)
