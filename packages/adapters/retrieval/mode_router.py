from __future__ import annotations

from typing import Any, Dict

from packages.core.domain.interfaces import Retriever
from packages.core.domain.models import RetrievedChunk


class ModeRouterRetriever(Retriever):
    def __init__(self, retrievers_by_mode: Dict[str, Retriever], fallback_mode: str = "hybrid_local") -> None:
        self._retrievers_by_mode = retrievers_by_mode
        self._fallback_mode = fallback_mode

    def retrieve(
        self,
        query: str,
        limit: int = 5,
        mode: str = "hybrid_local",
        **kwargs: Any,
    ) -> list[RetrievedChunk]:
        retriever = self._retrievers_by_mode.get(mode) or self._retrievers_by_mode[self._fallback_mode]
        return retriever.retrieve(query=query, limit=limit, mode=mode, **kwargs)
