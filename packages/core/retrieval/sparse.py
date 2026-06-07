from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Iterable


def tokenize(text: str) -> list[str]:
    return re.findall(r"[\w\u0370-\u03FF]+", text.lower(), flags=re.UNICODE)


def build_idf(docs_tokens: list[list[str]]) -> dict[str, float]:
    n = len(docs_tokens)
    df: Counter[str] = Counter()
    for tokens in docs_tokens:
        for term in set(tokens):
            df[term] += 1
    return {term: math.log((n - freq + 0.5) / (freq + 0.5) + 1.0) for term, freq in df.items()}


def bm25_score(query_tokens: list[str], doc_tokens: list[str], *, idf: dict[str, float], avgdl: float, k1: float = 1.5, b: float = 0.75) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    tf = Counter(doc_tokens)
    dl = len(doc_tokens)
    score = 0.0
    for term in query_tokens:
        if term not in tf:
            continue
        freq = tf[term]
        idf_val = idf.get(term, 0.0)
        denom = freq + k1 * (1.0 - b + b * (dl / max(avgdl, 1.0)))
        score += idf_val * (freq * (k1 + 1.0)) / max(denom, 1e-9)
    return score


def tfidf_score(query_tokens: list[str], doc_tokens: list[str], *, idf: dict[str, float]) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    tf = Counter(doc_tokens)
    dl = max(len(doc_tokens), 1)
    score = 0.0
    for term in set(query_tokens):
        if term not in tf:
            continue
        tf_val = tf[term] / dl
        score += tf_val * idf.get(term, 0.0)
    return score


def score_documents(
    query: str,
    documents: Iterable[tuple[str, str]],
    *,
    method: str = "bm25",
) -> dict[str, float]:
    """Return doc_id -> sparse score."""
    docs = [(doc_id, tokenize(text)) for doc_id, text in documents]
    if not docs:
        return {}
    idf = build_idf([tokens for _, tokens in docs])
    avgdl = sum(len(tokens) for _, tokens in docs) / max(len(docs), 1)
    query_tokens = tokenize(query)
    scores: dict[str, float] = {}
    for doc_id, doc_tokens in docs:
        if method == "tfidf":
            scores[doc_id] = tfidf_score(query_tokens, doc_tokens, idf=idf)
        else:
            scores[doc_id] = bm25_score(query_tokens, doc_tokens, idf=idf, avgdl=avgdl)
    return scores


def normalize_scores(scores: dict[str, float], *, method: str = "minmax") -> dict[str, float]:
    if not scores:
        return {}
    values = list(scores.values())
    if method == "zscore":
        mean = sum(values) / len(values)
        var = sum((v - mean) ** 2 for v in values) / max(len(values), 1)
        std = math.sqrt(var) if var > 0 else 1.0
        out = {k: max(0.0, min(1.0, 0.5 + 0.5 * ((v - mean) / std))) for k, v in scores.items()}
        return out
    min_v = min(values)
    max_v = max(values)
    if max_v - min_v < 1e-12:
        return {k: (1.0 if v > 0 else 0.0) for k, v in scores.items()}
    return {k: (v - min_v) / (max_v - min_v) for k, v in scores.items()}
