from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from packages.adapters.retrieval.embedding_utils import cosine_similarity, deterministic_embed
from packages.core.domain.interfaces import Retriever
from packages.core.domain.models import RetrievedChunk


class VectorIndexRetriever(Retriever):
    def __init__(self, vector_index_path: str) -> None:
        self._vector_index_path = Path(vector_index_path)
        self._docs = self._load_docs()

    def _load_docs(self) -> List[dict]:
        if not self._vector_index_path.exists():
            return []
        payload = json.loads(self._vector_index_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload.get("documents", [])
        return []

    def retrieve(
        self,
        query: str,
        limit: int = 5,
        mode: str = "vector_db",
        **kwargs: Any,
    ) -> List[RetrievedChunk]:
        qv = deterministic_embed(query)
        scored: List[RetrievedChunk] = []
        for doc in self._docs:
            dv = doc.get("embedding", [])
            if not dv:
                continue
            score = cosine_similarity(qv, dv)
            if score <= 0:
                continue
            scored.append(
                RetrievedChunk(
                    id=str(doc.get("id", "")),
                    text=f"{doc.get('title', '')}\n{doc.get('content', '')}".strip(),
                    source=doc.get("source_url", "vector://index"),
                    score=float(score),
                    metadata={
                        "connector": "vector_db",
                        "title": doc.get("title", ""),
                        "language": doc.get("language", "en"),
                    },
                )
            )
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]
