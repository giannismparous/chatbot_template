from __future__ import annotations

from dataclasses import dataclass, field

from packages.core.domain.models import PublicSource, RetrievedChunk


@dataclass
class CitedChunk:
    index: int
    chunk_id: str
    title: str
    content: str
    internal_url: str
    citation_url: str | None
    source_visibility: str
    is_faq: bool
    score: float


@dataclass
class CitationContext:
    chunks: list[CitedChunk]
    index_by_id: dict[str, int] = field(default_factory=dict)

    @property
    def valid_indices(self) -> set[int]:
        return {c.index for c in self.chunks}


@dataclass
class CitationResult:
    answer: str
    public_sources: list[PublicSource]
    valid_citations: set[int] = field(default_factory=set)
    stripped_citations: list[int] = field(default_factory=list)
    stripped_urls: list[str] = field(default_factory=list)


def cited_chunk_from_retrieved(index: int, chunk: RetrievedChunk) -> CitedChunk:
    meta = chunk.metadata or {}
    title = str(meta.get("title") or "Source").strip() or "Source"
    internal = str(meta.get("internal_url") or chunk.source or "")
    return CitedChunk(
        index=index,
        chunk_id=str(chunk.id),
        title=title,
        content=chunk.text,
        internal_url=internal,
        citation_url=meta.get("citation_url"),
        source_visibility=str(meta.get("source_visibility", "internal")),
        is_faq=bool(meta.get("is_faq")),
        score=float(chunk.score),
    )
