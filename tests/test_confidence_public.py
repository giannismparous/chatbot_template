from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from packages.core.chat.confidence_public import compute_retrieval_confidence, confidence_from_score


@dataclass
class _Doc:
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


def test_confidence_from_score_faq_hit_is_high() -> None:
    conf = confidence_from_score(0.45, faq_hit=True)
    assert conf.level == "high"


def test_compute_retrieval_confidence_faq_boost() -> None:
    docs = [_Doc(0.45, {"is_faq": True}), _Doc(0.20)]
    assert compute_retrieval_confidence(docs) >= 0.88


def test_compute_retrieval_confidence_citations_boost() -> None:
    docs = [_Doc(0.42), _Doc(0.38)]
    score = compute_retrieval_confidence(docs, citation_count=2)
    assert score >= 0.75


def test_compute_retrieval_confidence_empty() -> None:
    assert compute_retrieval_confidence([]) == 0.0
