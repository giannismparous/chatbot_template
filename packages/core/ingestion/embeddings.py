from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from packages.core.ingestion.embedding_cache import read_cached_vector, write_cached_vector
from packages.core.ingestion.models import IngestionSettings, KnowledgeChunk
from packages.core.ports.embedding_provider import EmbeddingProvider

ZERO_VECTOR_EPSILON = 1e-12


class EmbeddingValidationError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def chunk_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_vector(vector: list[float], *, expected_dims: int | None = None) -> None:
    if not vector:
        raise EmbeddingValidationError("EMPTY_VECTOR", "embedding vector is empty")
    if expected_dims is not None and len(vector) != expected_dims:
        raise EmbeddingValidationError(
            "WRONG_DIM",
            f"expected {expected_dims} dimensions, got {len(vector)}",
        )
    if all(abs(v) < ZERO_VECTOR_EPSILON for v in vector):
        raise EmbeddingValidationError("ZERO_VECTOR", "embedding vector is all zeros")


@dataclass
class VectorRecord:
    chunk_id: str
    source_id: str
    embedding: list[float]


@dataclass
class EmbeddingRunStats:
    embedded: int = 0
    cached: int = 0
    failed: int = 0
    carried_forward: int = 0
    cache_hits: int = 0
    provider_calls: int = 0


@dataclass
class EmbeddingRunResult:
    vectors_by_chunk_id: dict[str, list[float]] = field(default_factory=dict)
    stats: EmbeddingRunStats = field(default_factory=EmbeddingRunStats)
    embedding_dims: int | None = None


def embed_pending_chunks(
    *,
    clients_root: Any,
    client_id: str,
    chunks: list[KnowledgeChunk],
    carried_vectors: dict[str, list[float]],
    settings: IngestionSettings,
    provider: EmbeddingProvider,
) -> EmbeddingRunResult:
    result = EmbeddingRunResult()
    expected_dims = provider.expected_dims

    for chunk_id, vector in carried_vectors.items():
        try:
            validate_vector(vector, expected_dims=expected_dims)
        except EmbeddingValidationError:
            continue
        result.vectors_by_chunk_id[chunk_id] = vector
        result.stats.carried_forward += 1
        if expected_dims is None:
            expected_dims = len(vector)
        result.embedding_dims = expected_dims

    pending: list[KnowledgeChunk] = []
    for chunk in chunks:
        if chunk.embedding_status in ("embedded", "skipped_unchanged"):
            if chunk.id in carried_vectors:
                chunk.embedding_status = "skipped_unchanged"
                chunk.embedding_model = settings.embedding_model
                continue
        if chunk.embedding_status == "failed":
            continue
        pending.append(chunk)

    batch: list[KnowledgeChunk] = []
    batch_texts: list[str] = []

    def _flush_batch() -> None:
        nonlocal expected_dims, batch, batch_texts
        if not batch:
            return
        result.stats.provider_calls += 1
        try:
            vectors = provider.embed_texts(batch_texts, model=settings.embedding_model)
        except Exception as exc:
            for chunk in batch:
                chunk.embedding_status = "failed"
                result.stats.failed += 1
                if not chunk.embedding_error_code:
                    chunk.embedding_error_code = "EMBED_API_ERROR"
                    chunk.embedding_error_detail = str(exc)
            batch = []
            batch_texts = []
            return

        for chunk, vector in zip(batch, vectors):
            _store_embedding(
                clients_root=clients_root,
                client_id=client_id,
                chunk=chunk,
                vector=vector,
                settings=settings,
                result=result,
                expected_dims=expected_dims,
            )
            if result.embedding_dims and expected_dims is None:
                expected_dims = result.embedding_dims
        batch = []
        batch_texts = []

    for chunk in pending:
        if settings.cache_embeddings:
            cached = read_cached_vector(
                clients_root,
                client_id,
                content_hash=chunk.content_hash,
                embedding_model=settings.embedding_model,
            )
            if cached is not None:
                result.stats.cache_hits += 1
                try:
                    validate_vector(cached, expected_dims=expected_dims)
                    result.vectors_by_chunk_id[chunk.id] = cached
                    chunk.embedding_status = "embedded"
                    chunk.embedding_model = settings.embedding_model
                    result.stats.cached += 1
                    if expected_dims is None:
                        expected_dims = len(cached)
                    result.embedding_dims = expected_dims
                    continue
                except EmbeddingValidationError as exc:
                    chunk.embedding_status = "failed"
                    chunk.embedding_error_code = exc.code
                    chunk.embedding_error_detail = exc.detail
                    result.stats.failed += 1
                    continue

        batch.append(chunk)
        batch_texts.append(chunk.content)
        if len(batch) >= settings.embed_batch_size:
            _flush_batch()

    _flush_batch()
    return result


def _store_embedding(
    *,
    clients_root: Any,
    client_id: str,
    chunk: KnowledgeChunk,
    vector: list[float],
    settings: IngestionSettings,
    result: EmbeddingRunResult,
    expected_dims: int | None,
) -> None:
    try:
        validate_vector(vector, expected_dims=expected_dims)
    except EmbeddingValidationError as exc:
        chunk.embedding_status = "failed"
        chunk.embedding_error_code = exc.code
        chunk.embedding_error_detail = exc.detail
        result.stats.failed += 1
        return

    dims = len(vector)
    result.embedding_dims = dims
    result.vectors_by_chunk_id[chunk.id] = vector
    chunk.embedding_status = "embedded"
    chunk.embedding_model = settings.embedding_model
    result.stats.embedded += 1

    if settings.cache_embeddings:
        write_cached_vector(
            clients_root,
            client_id,
            content_hash=chunk.content_hash,
            embedding_model=settings.embedding_model,
            vector=vector,
            embedding_dims=dims,
        )
