from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PublicConfidence:
    level: str
    reason: str


def confidence_from_score(
    score: float,
    *,
    no_context: bool = False,
    crisis: bool = False,
    faq_hit: bool = False,
) -> PublicConfidence:
    if crisis:
        return PublicConfidence(level="none", reason="Crisis safety response.")
    if no_context or score <= 0.0:
        return PublicConfidence(level="none", reason="No approved knowledge found for this question.")
    if faq_hit or score >= 0.7:
        return PublicConfidence(level="high", reason="Strong document match.")
    if score >= 0.35:
        return PublicConfidence(level="medium", reason="Moderate document match; answer may be incomplete.")
    return PublicConfidence(level="low", reason="Weak document match; verify with official sources.")


def compute_retrieval_confidence(
    docs,
    *,
    citation_count: int = 0,
) -> float:
    """Map retrieval + citation signals to a 0-1 confidence score."""
    if not docs:
        return 0.0
    scores = [float(d.score) for d in docs]
    max_score = max(scores)
    avg_score = sum(scores) / len(scores)
    has_faq = any((d.metadata or {}).get("is_faq") for d in docs)

    if has_faq:
        return min(1.0, max(max_score, 0.88))
    if citation_count >= 2 and max_score >= 0.30:
        return min(1.0, max(max_score, 0.75))
    if citation_count >= 1 and max_score >= 0.30:
        return min(1.0, max(max_score * 0.85, avg_score, 0.65))
    blended = max_score * 0.65 + avg_score * 0.35
    return min(1.0, round(blended, 3))
