from __future__ import annotations

from typing import Any

from packages.core.retrieval.models import IndexedChunk
from packages.core.retrieval.sparse import tokenize


def apply_rules(
    chunk: IndexedChunk,
    query: str,
    rules: dict[str, Any],
) -> float:
    delta = 0.0
    query_tokens = set(tokenize(query))
    blob = f"{chunk.title}\n{chunk.content}\n{chunk.internal_url}".lower()

    domain_boost = float(rules.get("domain_boost", 0.55))
    domain_penalty_factor = float(rules.get("domain_penalty_factor", 0.12))

    for pattern in rules.get("domain_patterns") or []:
        if not isinstance(pattern, dict):
            continue
        triggers = [str(t).lower() for t in (pattern.get("triggers") or [])]
        url_parts = [str(u).lower() for u in (pattern.get("url_contains") or [])]
        trigger_hit = any(t in query.lower() for t in triggers)
        url_hit = any(u in blob for u in url_parts) if url_parts else True
        if trigger_hit and url_hit:
            delta += domain_boost
        elif triggers and trigger_hit and url_parts and not url_hit:
            delta -= domain_boost * domain_penalty_factor

    for boost in rules.get("topic_boosts") or []:
        if not isinstance(boost, dict):
            continue
        q_tokens = {str(t).lower() for t in (boost.get("query_tokens") or [])}
        b_tokens = {str(t).lower() for t in (boost.get("blob_tokens") or [])}
        if q_tokens & query_tokens and (not b_tokens or b_tokens & set(tokenize(blob))):
            delta += float(boost.get("add", 0.25))

    for penalty in rules.get("penalties") or []:
        if not isinstance(penalty, dict):
            continue
        url_parts = [str(u).lower() for u in (penalty.get("url_contains") or [])]
        if any(u in blob for u in url_parts):
            factor = float(penalty.get("factor", 0.5))
            delta -= abs(1.0 - factor)

    return delta
