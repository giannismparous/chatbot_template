from __future__ import annotations

from typing import Any, Dict, List

from packages.core.domain.interfaces import KnowledgeConnector, Retriever
from packages.core.domain.models import RetrievedChunk


class HybridFederatedRetriever(Retriever):
    def __init__(self, connectors: Dict[str, KnowledgeConnector], source_weights: Dict[str, float] | None = None) -> None:
        self._connectors = connectors
        self._source_weights = source_weights or {}

    def retrieve(
        self,
        query: str,
        limit: int = 5,
        mode: str = "hybrid_local",
        **kwargs: Any,
    ) -> List[RetrievedChunk]:
        merged: List[RetrievedChunk] = []
        for source_name, connector in self._connectors.items():
            docs = connector.search(query, limit=max(limit * 2, 10), **kwargs)
            weight = self._source_weights.get(source_name, 1.0)
            for d in docs:
                d.score = d.score * weight
            merged.extend(docs)

        # Deduplicate by text hash to avoid repeated chunks across connectors.
        dedup: Dict[str, RetrievedChunk] = {}
        for doc in merged:
            key = f"{doc.source}:{doc.text[:180]}"
            if key not in dedup or dedup[key].score < doc.score:
                dedup[key] = doc

        ranked = sorted(dedup.values(), key=lambda x: x.score, reverse=True)
        return ranked[:limit]
