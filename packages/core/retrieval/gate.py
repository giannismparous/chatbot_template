from __future__ import annotations

from packages.core.retrieval.models import CandidateScore, IndexedChunk, RetrievalOutcome
from packages.core.domain.models import RetrievedChunk


def apply_gate(
    selected: list[tuple[IndexedChunk, CandidateScore]],
    *,
    min_score: float,
    no_context_message: str,
) -> RetrievalOutcome:
    passed = [(chunk, cand) for chunk, cand in selected if cand.fusion_score >= min_score]
    if not passed:
        return RetrievalOutcome(
            chunks=[],
            no_context=True,
            no_context_message=no_context_message,
        )

    chunks = [
        RetrievedChunk(
            id=chunk.id,
            text=chunk.text,
            source=chunk.public_source,
            score=round(cand.fusion_score, 4),
            metadata={
                "title": chunk.title,
                "language": chunk.language,
                "connector": "tenant_retriever_v2",
                "citation_url": chunk.citation_url,
                "internal_url": chunk.internal_url,
                "source_visibility": chunk.source_visibility,
                "is_faq": cand.is_faq,
                "sparse_score": cand.sparse_score,
                "dense_score": cand.dense_score,
                "rule_delta": cand.rule_delta,
            },
        )
        for chunk, cand in passed
    ]
    return RetrievalOutcome(chunks=chunks, no_context=False)
