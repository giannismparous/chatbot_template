from __future__ import annotations

from typing import Any, Dict, Iterable, List

from packages.core.domain.interfaces import VectorStore


class MemoryVectorStore(VectorStore):
    def __init__(self) -> None:
        self._items: List[Dict[str, Any]] = []

    def upsert(self, items: Iterable[Dict[str, Any]]) -> None:
        self._items.extend(items)

    def query(self, vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        # Placeholder for semantic similarity implementation.
        return self._items[:top_k]
