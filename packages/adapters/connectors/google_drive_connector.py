from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from packages.core.domain.interfaces import KnowledgeConnector
from packages.core.domain.models import RetrievedChunk


class GoogleDriveConnector(KnowledgeConnector):
    """Deprecated: legacy federated connector reading packages/config/defaults/google_drive_index.json.

    New tenant Drive content uses drive_sources → drive_cache → ingest → eval → deploy.
    """
    def __init__(self, drive_index_path: str) -> None:
        self._drive_index_path = Path(drive_index_path)
        self._docs = self._load_docs()

    def _load_docs(self) -> List[dict]:
        if not self._drive_index_path.exists():
            return []
        with self._drive_index_path.open("r", encoding="utf-8") as f:
            payload = json.load(f) or {}
        return payload.get("documents", [])

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
                    source=doc.get("url", doc.get("source", "google_drive")),
                    score=float(score) / max(1, len(query_tokens)),
                    metadata={
                        "title": doc.get("title", ""),
                        "connector": "google_drive",
                        "file_id": doc.get("file_id", ""),
                    },
                )
            )
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]
