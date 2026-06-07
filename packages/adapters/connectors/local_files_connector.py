from __future__ import annotations

import json
from pathlib import Path
from typing import List

from packages.core.domain.interfaces import KnowledgeConnector
from packages.core.domain.models import RetrievedChunk


class LocalFilesConnector(KnowledgeConnector):
    def __init__(self, knowledge_path: str) -> None:
        self._knowledge_path = Path(knowledge_path)
        self._docs = self._load_docs()

    def _load_docs(self) -> List[dict]:
        if not self._knowledge_path.exists():
            return []
        with self._knowledge_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            return payload.get("documents", [])
        if isinstance(payload, list):
            return payload
        return []

    def search(self, query: str, limit: int = 10, **kwargs: Any) -> List[RetrievedChunk]:
        query_tokens = [t.strip().lower() for t in query.split() if t.strip()]
        scored: List[RetrievedChunk] = []
        for doc in self._docs:
            text = f"{doc.get('title', '')}\n{doc.get('content', '')}"
            hay = text.lower()
            score = sum(1 for t in query_tokens if t in hay)
            if score <= 0:
                continue
            scored.append(
                RetrievedChunk(
                    id=str(doc.get("id", "")),
                    text=text,
                    source=doc.get("url", doc.get("source", "local_file")),
                    score=float(score) / max(1, len(query_tokens)),
                    metadata={
                        "title": doc.get("title", ""),
                        "language": doc.get("language", "unknown"),
                        "connector": "local_files",
                    },
                )
            )
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]
