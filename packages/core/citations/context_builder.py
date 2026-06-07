from __future__ import annotations

from packages.core.citations.models import CitationContext, CitedChunk, cited_chunk_from_retrieved
from packages.core.domain.models import RetrievedChunk


def _citation_order_key(chunk: RetrievedChunk) -> tuple[int, float, str]:
    """Public mapped sources first so [n] markers map to clickable URLs."""
    meta = chunk.metadata or {}
    visibility = str(meta.get("source_visibility", "internal"))
    citation_url = meta.get("citation_url")
    is_faq = bool(meta.get("is_faq"))
    if visibility == "public" and citation_url:
        tier = 0
    elif is_faq:
        tier = 2
    else:
        tier = 1
    return (tier, -float(chunk.score or 0.0), chunk.id)


def build_citation_context(chunks: list[RetrievedChunk]) -> CitationContext:
    ordered = sorted(chunks, key=_citation_order_key)
    cited: list[CitedChunk] = []
    index_by_id: dict[str, int] = {}
    for idx, chunk in enumerate(ordered, start=1):
        item = cited_chunk_from_retrieved(idx, chunk)
        cited.append(item)
        index_by_id[item.chunk_id] = idx
    return CitationContext(chunks=cited, index_by_id=index_by_id)


def format_numbered_context(context: CitationContext, *, content_limit: int = 1000) -> str:
    lines = [
        "Context (use ONLY these numbered sources; cite factual claims inline as [n]):",
        "",
    ]
    for chunk in context.chunks:
        lines.append(f"[{chunk.index}] Title: {chunk.title}")
        if chunk.source_visibility == "public" and chunk.citation_url:
            lines.append(f"Public URL: {chunk.citation_url}")
        body = chunk.content[:content_limit]
        lines.append(f"Content:\n{body}")
        lines.append("")
    return "\n".join(lines).strip()
