from __future__ import annotations

import os
from typing import Any, List

from packages.adapters.llm.gemini_adapter import GeminiAdapter
from packages.adapters.retrieval.embedding_utils import deterministic_embed
from packages.core.domain.interfaces import Retriever
from packages.core.domain.models import RetrievedChunk


class QdrantRetriever(Retriever):
    def __init__(self, qdrant: Any) -> None:
        self._qdrant = qdrant

    def _embed_query(self, query: str) -> List[float]:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        model = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
        if not api_key:
            return deterministic_embed(query)
        try:
            adapter = GeminiAdapter(api_key=api_key)
            return adapter.embed_texts([query], model=model)[0]
        except Exception:
            return deterministic_embed(query)

    def retrieve(
        self,
        query: str,
        limit: int = 5,
        mode: str = "vector_db",
        **kwargs: Any,
    ) -> List[RetrievedChunk]:
        qv = self._embed_query(query)
        try:
            docs = self._qdrant.query(vector=qv, top_k=limit)
        except Exception:
            return []
        out: List[RetrievedChunk] = []
        for d in docs:
            out.append(
                RetrievedChunk(
                    id=str(d.get("id", "")),
                    text=f"{d.get('title', '')}\n{d.get('content', '')}".strip(),
                    source=d.get("source_url", "qdrant://collection"),
                    score=float(d.get("score", 0.0)),
                    metadata={"connector": "qdrant", "language": d.get("language", "en")},
                )
            )
        return out
