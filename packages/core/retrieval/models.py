from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from packages.core.domain.models import RetrievedChunk


@dataclass
class IndexedChunk:
    id: str
    source_id: str
    title: str
    content: str
    internal_url: str
    citation_url: str | None
    source_visibility: str
    language: str = "unknown"
    embedding_status: str | None = None

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.content}".strip()

    @property
    def public_source(self) -> str:
        if self.citation_url and self.source_visibility == "public":
            return self.citation_url
        return self.internal_url


@dataclass
class TenantIndex:
    client_id: str
    version_id: str | None
    chunks: list[IndexedChunk]
    vectors_by_chunk_id: dict[str, list[float]] = field(default_factory=dict)
    embedding_model: str | None = None
    embedding_dims: int | None = None
    is_legacy: bool = False


@dataclass
class CandidateScore:
    chunk_id: str
    sparse_score: float = 0.0
    dense_score: float = 0.0
    faq_score: float = 0.0
    faq_triggers_matched: int = 0
    rule_delta: float = 0.0
    fusion_score: float = 0.0
    source: str = "sparse"
    is_faq: bool = False
    faq_id: str | None = None


@dataclass
class RetrievalOutcome:
    chunks: list[RetrievedChunk]
    no_context: bool = False
    no_context_message: str | None = None
    dense_used: bool = False
    dense_skip_reason: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
