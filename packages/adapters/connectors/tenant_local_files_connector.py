from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from packages.core.domain.interfaces import KnowledgeConnector
from packages.core.domain.models import RetrievedChunk
from packages.core.ingestion.paths import resolve_active_knowledge_index
from packages.core.tenant.paths import safe_client_id


class TenantLocalFilesConnector(KnowledgeConnector):
    """Reads active per-client knowledge_index; falls back to legacy shared defaults."""

    def __init__(self, *, clients_root: Path, legacy_fallback_path: str) -> None:
        self._clients_root = clients_root.resolve()
        self._legacy_path = Path(legacy_fallback_path)
        self._legacy_docs = self._load_index_payload(self._legacy_path)

    @staticmethod
    def _load_index_payload(path: Path) -> List[dict]:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        return TenantLocalFilesConnector._payload_to_docs(payload)

    @staticmethod
    def _payload_to_docs(payload: Any) -> List[dict]:
        if isinstance(payload, list):
            return [TenantLocalFilesConnector._normalize_item(item) for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            chunks = payload.get("chunks")
            if isinstance(chunks, list):
                return [
                    TenantLocalFilesConnector._normalize_item(item)
                    for item in chunks
                    if isinstance(item, dict)
                ]
            documents = payload.get("documents")
            if isinstance(documents, list):
                return [
                    TenantLocalFilesConnector._normalize_item(item)
                    for item in documents
                    if isinstance(item, dict)
                ]
        return []

    @staticmethod
    def _normalize_item(item: dict) -> dict:
        if "internal_url" in item or "source_visibility" in item or "citation_url" in item:
            return TenantLocalFilesConnector._chunk_to_doc(item)
        return TenantLocalFilesConnector._document_to_doc(item)

    @staticmethod
    def _document_to_doc(doc: dict) -> dict:
        url = doc.get("url") or doc.get("source") or "local_file"
        return {
            "id": doc.get("id", ""),
            "title": doc.get("title", ""),
            "content": doc.get("content", ""),
            "url": url,
            "language": doc.get("language", "unknown"),
            "citation_url": doc.get("citation_url"),
            "internal_url": doc.get("internal_url") or url,
            "source_visibility": doc.get("source_visibility", "internal"),
        }

    @staticmethod
    def _chunk_to_doc(chunk: dict) -> dict:
        citation = chunk.get("citation_url")
        internal = chunk.get("internal_url") or chunk.get("url") or "local_file"
        source_visibility = chunk.get("source_visibility", "internal")
        public_source = citation if citation and source_visibility == "public" else internal
        return {
            "id": chunk.get("id", ""),
            "title": chunk.get("title", ""),
            "content": chunk.get("content", ""),
            "url": public_source,
            "language": chunk.get("language", "unknown"),
            "citation_url": citation,
            "internal_url": internal,
            "source_visibility": source_visibility,
        }

    def _load_client_docs(self, client_id: str) -> List[dict]:
        index_path = resolve_active_knowledge_index(self._clients_root, client_id)
        if index_path is None:
            return self._legacy_docs
        return self._load_index_payload(index_path)

    def search(self, query: str, limit: int = 10, **kwargs: Any) -> List[RetrievedChunk]:
        client_id = kwargs.get("client_id")
        docs = self._legacy_docs
        if client_id:
            try:
                cid = safe_client_id(str(client_id))
                docs = self._load_client_docs(cid)
            except ValueError:
                return []

        query_tokens = [t.strip().lower() for t in query.split() if t.strip()]
        scored: List[RetrievedChunk] = []
        for doc in docs:
            text = f"{doc.get('title', '')}\n{doc.get('content', '')}"
            hay = text.lower()
            score = sum(1 for t in query_tokens if t in hay)
            if score <= 0:
                continue
            citation = doc.get("citation_url")
            visibility = doc.get("source_visibility", "internal")
            internal = doc.get("internal_url") or doc.get("url") or "local_file"
            source = citation if citation and visibility == "public" else internal
            scored.append(
                RetrievedChunk(
                    id=str(doc.get("id", "")),
                    text=text,
                    source=source,
                    score=float(score) / max(1, len(query_tokens)),
                    metadata={
                        "title": doc.get("title", ""),
                        "language": doc.get("language", "unknown"),
                        "connector": "tenant_local_files",
                        "citation_url": citation,
                        "internal_url": internal,
                        "source_visibility": visibility,
                    },
                )
            )
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]
