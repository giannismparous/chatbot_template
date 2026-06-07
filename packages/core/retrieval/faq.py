from __future__ import annotations

from typing import Any

from packages.core.retrieval.models import CandidateScore, IndexedChunk


def match_faq_entries(
    query: str,
    faq_config: dict[str, Any],
    *,
    base_score: float = 2.5,
) -> tuple[list[IndexedChunk], dict[str, CandidateScore]]:
    entries = faq_config.get("entries") or faq_config.get("faqs") or []
    if not isinstance(entries, list):
        return [], {}

    faq_chunks: list[IndexedChunk] = []
    scores: dict[str, CandidateScore] = {}
    normalized_query = query.lower()

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        triggers = entry.get("triggers") or []
        matched = [t for t in triggers if str(t).lower() in normalized_query]
        if not matched:
            continue
        faq_id = str(entry.get("id", f"faq-{len(faq_chunks)+1}"))
        chunk = IndexedChunk(
            id=faq_id,
            source_id=f"faq:{faq_id}",
            title=str(entry.get("question", entry.get("title", "FAQ"))),
            content=str(entry.get("answer", entry.get("content", ""))),
            internal_url=f"faq://{faq_id}",
            citation_url=entry.get("citation_url"),
            source_visibility=entry.get("source_visibility", "internal"),
            language=str(entry.get("language", "unknown")),
            embedding_status=None,
        )
        faq_chunks.append(chunk)
        scores[faq_id] = CandidateScore(
            chunk_id=faq_id,
            faq_score=base_score,
            faq_triggers_matched=len(matched),
            fusion_score=0.0,
            source="faq",
            is_faq=True,
            faq_id=faq_id,
        )
    return faq_chunks, scores
