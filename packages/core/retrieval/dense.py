from __future__ import annotations

import math

from packages.core.retrieval.sparse import tokenize


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def score_vectors(query_vector: list[float], vectors_by_chunk_id: dict[str, list[float]]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for chunk_id, vector in vectors_by_chunk_id.items():
        sim = cosine_similarity(query_vector, vector)
        if sim > 0:
            scores[chunk_id] = sim
    return scores


def token_jaccard(a: str, b: str) -> float:
    ta = set(tokenize(a))
    tb = set(tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
