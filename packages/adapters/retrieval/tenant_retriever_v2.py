from __future__ import annotations

from pathlib import Path
from typing import Any, List

from packages.adapters.embedding.gemini_embedding_adapter import GeminiEmbeddingAdapter
from packages.core.config.loader import TenantConfigLoader
from packages.core.domain.interfaces import Retriever
from packages.core.domain.models import RetrievedChunk
from packages.core.ports.embedding_provider import EmbeddingProvider
from packages.core.retrieval.models import RetrievalOutcome
from packages.core.retrieval.pipeline import TenantRetrievalPipeline


class TenantRetrieverV2(Retriever):
    """Per-client hybrid retrieval over active knowledge_index + optional vector_index."""

    def __init__(
        self,
        *,
        clients_root: Path,
        config_loader: TenantConfigLoader,
        legacy_fallback_path: str,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._pipeline = TenantRetrievalPipeline(
            clients_root=clients_root,
            config_loader=config_loader,
            legacy_fallback_path=Path(legacy_fallback_path),
            embedding_provider=embedding_provider,
        )

    @classmethod
    def build_default(
        cls,
        *,
        clients_root: Path,
        config_loader: TenantConfigLoader,
        legacy_fallback_path: str,
    ) -> TenantRetrieverV2:
        provider: EmbeddingProvider | None = None
        try:
            provider = GeminiEmbeddingAdapter.from_env(max_retries=2, backoff_base_ms=200, backoff_max_ms=2000)
        except RuntimeError:
            provider = None
        return cls(
            clients_root=clients_root,
            config_loader=config_loader,
            legacy_fallback_path=legacy_fallback_path,
            embedding_provider=provider,
        )

    def retrieve_with_outcome(
        self,
        query: str,
        limit: int = 5,
        mode: str = "hybrid_local",
        *,
        client_id: str | None = None,
        **kwargs: Any,
    ) -> RetrievalOutcome:
        del mode
        cid = client_id or kwargs.get("client_id")
        if not cid:
            return RetrievalOutcome(chunks=[], no_context=True)
        return self._pipeline.retrieve(query, client_id=str(cid), limit=limit)

    def retrieve(
        self,
        query: str,
        limit: int = 5,
        mode: str = "hybrid_local",
        **kwargs: Any,
    ) -> List[RetrievedChunk]:
        return self.retrieve_with_outcome(
            query,
            limit=limit,
            mode=mode,
            client_id=kwargs.get("client_id"),
        ).chunks
