from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from packages.core.config.loader import TenantConfigLoader
from packages.core.ports.embedding_provider import EmbeddingProvider
from packages.core.retrieval.dense import score_vectors
from packages.core.retrieval.faq import match_faq_entries
from packages.core.retrieval.fusion import fuse_scores
from packages.core.retrieval.gate import apply_gate
from packages.core.retrieval.index_loader import load_tenant_index
from packages.core.retrieval.mmr import apply_mmr
from packages.core.retrieval.models import CandidateScore, IndexedChunk, RetrievalOutcome
from packages.core.retrieval.query_normalize import normalize_query
from packages.core.retrieval.rules import apply_rules
from packages.core.retrieval.sparse import score_documents
from packages.core.tenant.paths import safe_client_id


class TenantRetrievalPipeline:
    def __init__(
        self,
        *,
        clients_root: Path,
        config_loader: TenantConfigLoader,
        legacy_fallback_path: Path,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._clients_root = clients_root.resolve()
        self._config_loader = config_loader
        self._legacy_fallback_path = legacy_fallback_path
        self._embedding_provider = embedding_provider

    def retrieve(
        self,
        query: str,
        *,
        client_id: str,
        limit: int = 5,
    ) -> RetrievalOutcome:
        cid = safe_client_id(client_id)
        merged = self._config_loader.load(cid)
        rules = merged.retrieval_rules or {}
        locale = merged.locale or {}
        faq = merged.faq or {}
        ingestion = merged.ingestion or {}

        gate_cfg = rules.get("gate") or {}
        min_score = float(gate_cfg.get("min_score", 0.18))
        no_context_message = str(
            gate_cfg.get(
                "no_context_message",
                "I could not find relevant information in the available sources.",
            )
        )
        output_cfg = rules.get("output") or {}
        send_to_model = min(int(output_cfg.get("send_to_model", 6)), max(limit, 1))
        pool_size = int((rules.get("sparse") or {}).get("pool_size", 25))

        normalized_query = normalize_query(query, locale)
        index = load_tenant_index(
            clients_root=self._clients_root,
            client_id=cid,
            legacy_fallback_path=self._legacy_fallback_path,
        )

        chunk_map: dict[str, IndexedChunk] = {c.id: c for c in index.chunks}
        candidates: dict[str, CandidateScore] = {}

        sparse_method = str((rules.get("sparse") or {}).get("method", "bm25"))
        sparse_scores = score_documents(
            normalized_query,
            ((c.id, c.text) for c in index.chunks),
            method=sparse_method,
        )
        sparse_ranked = sorted(sparse_scores.items(), key=lambda x: x[1], reverse=True)[:pool_size]
        for chunk_id, score in sparse_ranked:
            candidates[chunk_id] = CandidateScore(chunk_id=chunk_id, sparse_score=score, source="sparse")

        dense_used = False
        dense_skip_reason: str | None = None
        dense_cfg = rules.get("dense") or {}
        if not dense_cfg.get("enabled", True):
            dense_skip_reason = "disabled_by_config"
        elif not index.vectors_by_chunk_id:
            dense_skip_reason = "no_vector_index"
        else:
            expected_model = str(
                ingestion.get("embedding_model")
                or os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
            )
            if index.embedding_model and index.embedding_model != expected_model:
                dense_skip_reason = "model_mismatch"
            elif not self._embedding_provider:
                dense_skip_reason = "missing_api_key"
            else:
                try:
                    query_vectors = self._embedding_provider.embed_texts(
                        [normalized_query],
                        model=expected_model,
                    )
                    query_vector = query_vectors[0] if query_vectors else []
                    dense_scores = score_vectors(query_vector, index.vectors_by_chunk_id)
                    dense_pool = int(dense_cfg.get("pool_size", pool_size))
                    dense_ranked = sorted(dense_scores.items(), key=lambda x: x[1], reverse=True)[:dense_pool]
                    for chunk_id, score in dense_ranked:
                        cand = candidates.setdefault(chunk_id, CandidateScore(chunk_id=chunk_id))
                        cand.dense_score = score
                        if cand.source == "sparse":
                            cand.source = "hybrid"
                        else:
                            cand.source = "dense"
                    dense_used = bool(dense_ranked)
                except Exception:
                    dense_skip_reason = "embedding_error"

        faq_cfg = rules.get("faq") or {}
        faq_base = float(faq_cfg.get("base_score", 2.5))
        faq_chunks, faq_candidates = match_faq_entries(normalized_query, faq, base_score=faq_base)
        for faq_chunk in faq_chunks:
            chunk_map[faq_chunk.id] = faq_chunk
        candidates.update(faq_candidates)

        rules_section = rules.get("rules") or rules
        for chunk_id, cand in candidates.items():
            chunk = chunk_map.get(chunk_id)
            if chunk:
                cand.rule_delta = apply_rules(chunk, normalized_query, rules_section)

        candidates = fuse_scores(candidates, rules=rules)

        ranked = sorted(
            ((chunk_map[cid], cand) for cid, cand in candidates.items() if cid in chunk_map),
            key=lambda item: item[1].fusion_score,
            reverse=True,
        )
        retrieve_pool = int(output_cfg.get("retrieve_pool", 24))
        ranked = ranked[:retrieve_pool]

        mmr_cfg = rules.get("mmr") or {}
        if mmr_cfg.get("enabled", True):
            selected = apply_mmr(
                ranked,
                limit=send_to_model,
                lambda_=float(mmr_cfg.get("lambda", 0.7)),
                max_chunks_per_url=int(mmr_cfg.get("max_chunks_per_url", 2)),
            )
        else:
            selected = ranked[:send_to_model]

        outcome = apply_gate(selected, min_score=min_score, no_context_message=no_context_message)
        outcome.dense_used = dense_used
        outcome.dense_skip_reason = dense_skip_reason
        outcome.meta = {
            "client_id": cid,
            "version_id": index.version_id,
            "is_legacy": index.is_legacy,
            "normalized_query": normalized_query,
            "candidate_count": len(candidates),
        }
        return outcome
