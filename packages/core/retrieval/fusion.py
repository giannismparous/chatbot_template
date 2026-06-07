from __future__ import annotations

from typing import Any

from packages.core.retrieval.models import CandidateScore
from packages.core.retrieval.sparse import normalize_scores


def fuse_scores(
    candidates: dict[str, CandidateScore],
    *,
    rules: dict[str, Any],
) -> dict[str, CandidateScore]:
    fusion_cfg = rules.get("fusion") or {}
    faq_cfg = rules.get("faq") or {}
    w_sparse = float(fusion_cfg.get("w_sparse", 0.45))
    w_dense = float(fusion_cfg.get("w_dense", 0.35))
    w_faq = float(fusion_cfg.get("w_faq", 0.20))
    norm_method = str(fusion_cfg.get("normalize", "minmax"))

    sparse_map = {cid: c.sparse_score for cid, c in candidates.items()}
    dense_map = {cid: c.dense_score for cid, c in candidates.items()}
    norm_sparse = normalize_scores(sparse_map, method=norm_method)
    norm_dense = normalize_scores(dense_map, method=norm_method)

    strong_min = int(faq_cfg.get("strong_match_min_triggers", 2))
    strong_floor = float(faq_cfg.get("strong_match_floor", 0.85))

    for cid, cand in candidates.items():
        faq_component = 1.0 if cand.is_faq else 0.0
        fusion = (
            w_sparse * norm_sparse.get(cid, 0.0)
            + w_dense * norm_dense.get(cid, 0.0)
            + w_faq * faq_component
            + cand.rule_delta
        )
        if cand.is_faq and cand.faq_triggers_matched >= strong_min:
            fusion = max(fusion, strong_floor)
        cand.fusion_score = fusion

    return candidates
