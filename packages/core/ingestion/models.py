from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

SourceStatus = Literal["indexed", "skipped", "skipped_unchanged", "unsupported", "failed"]
SourceVisibility = Literal["internal", "public"]
EmbeddingStatus = Literal["not_embedded", "embedded", "failed", "skipped_unchanged"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class IngestionSettings:
    chunk_size: int = 800
    overlap: int = 100
    skip_files: list[str] = field(default_factory=list)
    allowed_extensions: list[str] = field(default_factory=lambda: [".txt", ".md", ".pdf", ".docx"])
    embed_enabled: bool = False
    embedding_model: str = "gemini-embedding-001"
    embed_batch_size: int = 16
    embed_max_retries: int = 3
    embed_backoff_base_ms: int = 500
    embed_backoff_max_ms: int = 30000
    cache_embeddings: bool = True
    skip_unchanged_sources: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> IngestionSettings:
        raw = data or {}
        return cls(
            chunk_size=int(raw.get("chunk_size", 800)),
            overlap=int(raw.get("overlap", 100)),
            skip_files=list(raw.get("skip_files") or []),
            allowed_extensions=[str(x) for x in (raw.get("allowed_extensions") or [".txt", ".md", ".pdf", ".docx"])],
            embed_enabled=bool(raw.get("embed_enabled", False)),
            embedding_model=str(raw.get("embedding_model", "gemini-embedding-001")),
            embed_batch_size=int(raw.get("embed_batch_size", 16)),
            embed_max_retries=int(raw.get("embed_max_retries", 3)),
            embed_backoff_base_ms=int(raw.get("embed_backoff_base_ms", 500)),
            embed_backoff_max_ms=int(raw.get("embed_backoff_max_ms", 30000)),
            cache_embeddings=bool(raw.get("cache_embeddings", True)),
            skip_unchanged_sources=bool(raw.get("skip_unchanged_sources", True)),
        )


@dataclass
class KnowledgeChunk:
    id: str
    source_id: str
    title: str
    content: str
    internal_url: str
    citation_url: str | None
    source_visibility: SourceVisibility
    language: str = "unknown"
    content_hash: str = ""
    embedding_status: EmbeddingStatus = "not_embedded"
    embedding_model: str | None = None
    embedding_error_code: str | None = None
    embedding_error_detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceRecord:
    source_id: str
    filename: str
    path: str
    content_hash: str | None
    status: SourceStatus
    reason: str | None
    indexed_at: str | None
    chunk_count: int
    error_stage: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    dependency_missing: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActiveManifest:
    active: str | None = None
    pending: str | None = None
    previous: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.active is not None:
            payload["active"] = self.active
        if self.pending is not None:
            payload["pending"] = self.pending
        if self.previous is not None:
            payload["previous"] = self.previous
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ActiveManifest:
        raw = data or {}
        return cls(
            active=raw.get("active"),
            pending=raw.get("pending"),
            previous=raw.get("previous"),
        )


@dataclass
class IngestReport:
    client_id: str
    version_id: str
    embed_enabled: bool
    sources_total: int = 0
    indexed: int = 0
    skipped: int = 0
    skipped_unchanged: int = 0
    unsupported: int = 0
    failed: int = 0
    chunks_total: int = 0
    embeddings_embedded: int = 0
    embeddings_cached: int = 0
    embeddings_carried_forward: int = 0
    embeddings_failed: int = 0
    provider_calls: int = 0
    extraction_errors_by_stage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IngestResult:
    client_id: str
    version_id: str
    chunk_count: int
    source_count: int
    indexed_count: int
    skipped_count: int
    skipped_unchanged_count: int
    unsupported_count: int
    failed_count: int
    embed_enabled: bool
    vector_count: int = 0
