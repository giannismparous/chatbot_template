from __future__ import annotations

from packages.core.retrieval.dense import token_jaccard
from packages.core.retrieval.models import CandidateScore, IndexedChunk


def apply_mmr(
    ranked: list[tuple[IndexedChunk, CandidateScore]],
    *,
    limit: int,
    lambda_: float,
    max_chunks_per_url: int,
) -> list[tuple[IndexedChunk, CandidateScore]]:
    selected: list[tuple[IndexedChunk, CandidateScore]] = []
    url_counts: dict[str, int] = {}
    remaining = list(ranked)

    while remaining and len(selected) < limit:
        best_idx = -1
        best_mmr = float("-inf")
        for idx, (chunk, cand) in enumerate(remaining):
            url = chunk.internal_url
            if url_counts.get(url, 0) >= max_chunks_per_url:
                continue
            if not selected:
                mmr = cand.fusion_score
            else:
                max_sim = max(token_jaccard(chunk.text, s[0].text) for s in selected)
                mmr = lambda_ * cand.fusion_score - (1.0 - lambda_) * max_sim
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = idx
        if best_idx < 0:
            break
        picked = remaining.pop(best_idx)
        selected.append(picked)
        url_counts[picked[0].internal_url] = url_counts.get(picked[0].internal_url, 0) + 1

    return selected
