from __future__ import annotations

from typing import Any, Dict, Iterable, List

from qdrant_client import QdrantClient
from qdrant_client.http import models


class QdrantAdapter:
    def __init__(self, url: str, api_key: str | None, collection: str, vector_size: int = 128) -> None:
        self._collection = collection
        self._vector_size = vector_size
        self._client = QdrantClient(url=url, api_key=api_key or None)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        collections = self._client.get_collections().collections
        names = {c.name for c in collections}
        if self._collection in names:
            return
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=models.VectorParams(size=self._vector_size, distance=models.Distance.COSINE),
        )

    def upsert(self, items: Iterable[Dict[str, Any]]) -> None:
        points = []
        for item in items:
            vec = item.get("embedding", [])
            payload = dict(item)
            payload.pop("embedding", None)
            point_id = str(item.get("id", ""))
            if not point_id:
                continue
            points.append(models.PointStruct(id=point_id, vector=vec, payload=payload))
        if points:
            self._client.upsert(collection_name=self._collection, points=points)

    def query(self, vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        hits = self._client.search(
            collection_name=self._collection,
            query_vector=vector,
            limit=top_k,
            with_payload=True,
        )
        out = []
        for h in hits:
            payload = dict(h.payload or {})
            payload["score"] = float(h.score)
            out.append(payload)
        return out
