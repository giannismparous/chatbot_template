from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import pytest

from packages.core.config.loader import TenantConfigLoader
from packages.core.domain.models import ChatMessage, ChatRequest
from packages.core.ingestion.manifest import write_active_manifest, write_knowledge_index
from packages.core.ingestion.models import ActiveManifest, KnowledgeChunk
from packages.core.ingestion.paths import (
    active_manifest_path,
    knowledge_index_path,
    source_manifest_path,
    vector_index_path,
)
from packages.core.orchestrator.chat_orchestrator import ChatOrchestrator
from packages.core.ports.embedding_provider import EmbeddingProvider
from packages.core.retrieval.models import RetrievalOutcome
from packages.adapters.retrieval.tenant_retriever_v2 import TenantRetrieverV2
from packages.core.retrieval.pipeline import TenantRetrievalPipeline
from packages.core.retrieval.query_normalize import normalize_query
from packages.core.retrieval.sparse import score_documents

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"
LEGACY = ROOT / "packages" / "config" / "defaults" / "knowledge.json"


class MockQueryEmbedder(EmbeddingProvider):
    def __init__(self, *, dim: int = 4) -> None:
        self.dim = dim
        self.calls = 0

    @property
    def expected_dims(self) -> int | None:
        return self.dim

    def embed_texts(self, texts: Sequence[str], *, model: str) -> list[list[float]]:
        self.calls += 1
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


class MockLLM:
    def __init__(self) -> None:
        self.called = False

    def generate(self, system_prompt, messages, model, temperature=0.2) -> str:
        self.called = True
        return "should not happen"


class MockRetriever:
    def __init__(self, outcome: RetrievalOutcome) -> None:
        self._outcome = outcome

    def retrieve_with_outcome(self, query, limit=5, mode="hybrid_local", **kwargs):
        return self._outcome

    def retrieve(self, query, limit=5, mode="hybrid_local", **kwargs):
        return self._outcome.chunks


def _loader(clients_root: Path) -> TenantConfigLoader:
    return TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)


def _write_client(clients_root: Path, client_id: str, *, extra_config: dict[str, Any] | None = None) -> None:
    config_dir = clients_root / client_id / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "client.yaml").write_text(
        f"client_id: {client_id}\ndisplay_name: {client_id}\ndomain_pack: generic\n",
        encoding="utf-8",
    )
    if extra_config:
        for name, content in extra_config.items():
            (config_dir / name).write_text(content, encoding="utf-8")
    (clients_root / client_id / "uploads").mkdir(parents=True, exist_ok=True)
    (clients_root / client_id / "indexes" / "versions").mkdir(parents=True, exist_ok=True)


def _write_active_knowledge(
    clients_root: Path,
    client_id: str,
    version_id: str,
    chunks: list[KnowledgeChunk],
    *,
    vectors: list[dict] | None = None,
    embedding_model: str = "gemini-embedding-001",
) -> None:
    write_knowledge_index(
        knowledge_index_path(clients_root, client_id, version_id),
        client_id=client_id,
        version_id=version_id,
        chunks=chunks,
    )
    source_manifest_path(clients_root, client_id, version_id).write_text("{}", encoding="utf-8")
    if vectors is not None:
        vector_index_path(clients_root, client_id, version_id).write_text(
            json.dumps(
                {
                    "client_id": client_id,
                    "version_id": version_id,
                    "embedding_model": embedding_model,
                    "embedding_dims": 4,
                    "vectors": vectors,
                }
            ),
            encoding="utf-8",
        )
    write_active_manifest(
        active_manifest_path(clients_root, client_id),
        ActiveManifest(active=version_id),
    )


def _pipeline(clients_root: Path, embedder: EmbeddingProvider | None = None) -> TenantRetrievalPipeline:
    return TenantRetrievalPipeline(
        clients_root=clients_root,
        config_loader=_loader(clients_root),
        legacy_fallback_path=LEGACY,
        embedding_provider=embedder,
    )


def _retriever(clients_root: Path, embedder: EmbeddingProvider | None = None) -> TenantRetrieverV2:
    return TenantRetrieverV2(
        clients_root=clients_root,
        config_loader=_loader(clients_root),
        legacy_fallback_path=str(LEGACY),
        embedding_provider=embedder,
    )


def test_sparse_bm25_ranks_relevant_chunk() -> None:
    scores = score_documents(
        "widget pricing",
        [
            ("a", "Our widget pricing is competitive."),
            ("b", "Unrelated content about weather."),
        ],
        method="bm25",
    )
    assert scores["a"] > scores["b"]


def test_query_normalize_nfc_and_greeklish() -> None:
    locale = {
        "query_normalization": {"nfc": True, "lowercase": True},
        "greeklish_enabled": True,
        "greeklish_map": {"ωραριο": "ωράριο"},
    }
    assert "ωράριο" in normalize_query("ωραριο", locale)


def test_sparse_only_when_no_vector_index(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a")
    _write_active_knowledge(
        clients_root,
        "tenant_a",
        "v1",
        [
            KnowledgeChunk(
                id="c1",
                source_id="s1",
                title="Guide",
                content="Alpha retrieval marker sparseonly99",
                internal_url="uploads/a.txt",
                citation_url=None,
                source_visibility="internal",
            )
        ],
    )
    embedder = MockQueryEmbedder()
    outcome = _pipeline(clients_root, embedder).retrieve(
        "sparseonly99",
        client_id="tenant_a",
        limit=3,
    )
    assert outcome.chunks
    assert embedder.calls == 0
    assert outcome.dense_skip_reason == "no_vector_index"


def test_dense_used_when_vector_index_present(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a")
    _write_active_knowledge(
        clients_root,
        "tenant_a",
        "v1",
        [
            KnowledgeChunk(
                id="c1",
                source_id="s1",
                title="Dense",
                content="dense marker densehit77",
                internal_url="uploads/a.txt",
                citation_url=None,
                source_visibility="internal",
            )
        ],
        vectors=[{"chunk_id": "c1", "source_id": "s1", "embedding": [1.0, 0.0, 0.0, 0.0]}],
    )
    embedder = MockQueryEmbedder()
    outcome = _pipeline(clients_root, embedder).retrieve("densehit77", client_id="tenant_a", limit=3)
    assert outcome.dense_used is True
    assert embedder.calls == 1


def test_dense_skipped_on_model_mismatch(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(
        clients_root,
        "tenant_a",
        extra_config={"ingestion.yaml": "embedding_model: expected-model\n"},
    )
    _write_active_knowledge(
        clients_root,
        "tenant_a",
        "v1",
        [
            KnowledgeChunk(
                id="c1",
                source_id="s1",
                title="T",
                content="mismatch marker mismatch55",
                internal_url="uploads/a.txt",
                citation_url=None,
                source_visibility="internal",
            )
        ],
        vectors=[{"chunk_id": "c1", "source_id": "s1", "embedding": [1.0, 0.0, 0.0, 0.0]}],
        embedding_model="other-model",
    )
    embedder = MockQueryEmbedder()
    outcome = _pipeline(clients_root, embedder).retrieve("mismatch55", client_id="tenant_a", limit=3)
    assert outcome.dense_skip_reason == "model_mismatch"
    assert embedder.calls == 0
    assert outcome.chunks


def test_faq_injected_as_candidate(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(
        clients_root,
        "tenant_a",
        extra_config={
            "faq.json": json.dumps(
                {
                    "entries": [
                        {
                            "id": "faq-hours",
                            "triggers": ["hours", "ωράριο"],
                            "question": "Hours?",
                            "answer": "Nine to five support hours.",
                        }
                    ]
                }
            )
        },
    )
    _write_active_knowledge(
        clients_root,
        "tenant_a",
        "v1",
        [
            KnowledgeChunk(
                id="c1",
                source_id="s1",
                title="Other",
                content="nothing relevant here",
                internal_url="uploads/a.txt",
                citation_url=None,
                source_visibility="internal",
            )
        ],
    )
    outcome = _pipeline(clients_root).retrieve("support hours", client_id="tenant_a", limit=3)
    assert any(c.metadata.get("is_faq") for c in outcome.chunks)


def test_min_score_gate_sets_no_context(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(
        clients_root,
        "tenant_a",
        extra_config={"retrieval_rules.yaml": "gate:\n  min_score: 0.99\n"},
    )
    _write_active_knowledge(
        clients_root,
        "tenant_a",
        "v1",
        [
            KnowledgeChunk(
                id="c1",
                source_id="s1",
                title="Low",
                content="low score content gate123",
                internal_url="uploads/a.txt",
                citation_url=None,
                source_visibility="internal",
            )
        ],
    )
    outcome = _pipeline(clients_root).retrieve("gate123", client_id="tenant_a", limit=3)
    assert outcome.no_context is True
    assert outcome.chunks == []


def test_orchestrator_skips_llm_on_no_context(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a")
    llm = MockLLM()
    outcome = RetrievalOutcome(chunks=[], no_context=True, no_context_message="No relevant sources.")
    orchestrator = ChatOrchestrator(
        llm_provider=llm,
        retriever=MockRetriever(outcome),
        prompt_policy=_DummyPolicy(),
        default_model="test",
        config_loader=_loader(clients_root),
    )
    res = orchestrator.answer(
        ChatRequest(client_id="tenant_a", message="hello", history=[], top_k=3)
    )
    assert res.answer == "No relevant sources."
    assert res.sources == []
    assert res.trace.get("no_context") is True
    assert res.escalation is not None
    assert res.escalation.type == "dont_know"
    assert llm.called is False


class _DummyPolicy:
    def build_system_prompt(self, client_id: str, mode: str) -> str:
        return "system"


def test_tenant_isolation(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    for cid, marker in (("tenant_a", "alpha iso marker"), ("tenant_b", "beta iso marker")):
        _write_client(clients_root, cid)
        _write_active_knowledge(
            clients_root,
            cid,
            "v1",
            [
                KnowledgeChunk(
                    id="c1",
                    source_id="s1",
                    title="Doc",
                    content=marker,
                    internal_url="uploads/a.txt",
                    citation_url=None,
                    source_visibility="internal",
                )
            ],
        )
    pipe = _pipeline(clients_root)
    a = pipe.retrieve("alpha iso", client_id="tenant_a", limit=3)
    b = pipe.retrieve("beta iso", client_id="tenant_b", limit=3)
    assert any("alpha" in c.text.lower() for c in a.chunks)
    assert not any("beta" in c.text.lower() for c in a.chunks)
    assert any("beta" in c.text.lower() for c in b.chunks)


def test_legacy_fallback_for_unmigrated_client(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        json.dumps(
            [
                {
                    "id": "legacy-1",
                    "title": "Legacy",
                    "content": "legacy fallback marker legacy88",
                    "url": "internal://legacy",
                }
            ]
        ),
        encoding="utf-8",
    )
    _write_client(clients_root, "unmigrated")
    pipe = TenantRetrievalPipeline(
        clients_root=clients_root,
        config_loader=_loader(clients_root),
        legacy_fallback_path=legacy,
        embedding_provider=None,
    )
    outcome = pipe.retrieve("legacy88", client_id="unmigrated", limit=3)
    assert outcome.chunks
    assert outcome.meta.get("is_legacy") is True


def test_mmr_max_chunks_per_url(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a")
    chunks = []
    for i in range(4):
        chunks.append(
            KnowledgeChunk(
                id=f"c{i}",
                source_id="s1",
                title=f"Part {i}",
                content=f"same url diversity marker divers42 part {i}",
                internal_url="uploads/same.txt",
                citation_url=None,
                source_visibility="internal",
            )
        )
    _write_active_knowledge(clients_root, "tenant_a", "v1", chunks)
    outcome = _pipeline(clients_root).retrieve("divers42", client_id="tenant_a", limit=5)
    same_url = [c for c in outcome.chunks if c.metadata.get("internal_url") == "uploads/same.txt"]
    assert len(same_url) <= 2


def test_retriever_has_no_last_outcome_attribute(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a")
    retriever = _retriever(clients_root)
    assert not hasattr(retriever, "last_outcome")
    assert not hasattr(retriever, "_last_outcome")


def test_retrieve_with_outcome_returns_no_context_directly(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(
        clients_root,
        "tenant_a",
        extra_config={"retrieval_rules.yaml": "gate:\n  min_score: 0.99\n"},
    )
    _write_active_knowledge(
        clients_root,
        "tenant_a",
        "v1",
        [
            KnowledgeChunk(
                id="c1",
                source_id="s1",
                title="T",
                content="outcome gate marker outgate11",
                internal_url="uploads/a.txt",
                citation_url=None,
                source_visibility="internal",
            )
        ],
    )
    retriever = _retriever(clients_root)
    outcome = retriever.retrieve_with_outcome("outgate11", client_id="tenant_a", limit=3)
    assert outcome.no_context is True
    assert outcome.chunks == []


def test_retrieve_compat_returns_chunks(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a")
    _write_active_knowledge(
        clients_root,
        "tenant_a",
        "v1",
        [
            KnowledgeChunk(
                id="c1",
                source_id="s1",
                title="T",
                content="compat marker compat77",
                internal_url="uploads/a.txt",
                citation_url=None,
                source_visibility="internal",
            )
        ],
    )
    retriever = _retriever(clients_root)
    chunks = retriever.retrieve("compat77", client_id="tenant_a", limit=3)
    assert chunks
    assert chunks[0].id == "c1"


def test_sequential_retrievals_do_not_share_outcome_state(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a")
    _write_client(
        clients_root,
        "tenant_b",
        extra_config={"retrieval_rules.yaml": "gate:\n  min_score: 0.99\n"},
    )
    _write_active_knowledge(
        clients_root,
        "tenant_a",
        "v1",
        [
            KnowledgeChunk(
                id="c1",
                source_id="s1",
                title="A",
                content="sequential marker seqstate42 tenant a",
                internal_url="uploads/a.txt",
                citation_url=None,
                source_visibility="internal",
            )
        ],
    )
    _write_active_knowledge(
        clients_root,
        "tenant_b",
        "v1",
        [
            KnowledgeChunk(
                id="c1",
                source_id="s1",
                title="B",
                content="sequential marker seqstate42 tenant b",
                internal_url="uploads/b.txt",
                citation_url=None,
                source_visibility="internal",
            )
        ],
    )
    retriever = _retriever(clients_root)
    first = retriever.retrieve_with_outcome("seqstate42 tenant a", client_id="tenant_a", limit=3)
    second = retriever.retrieve_with_outcome("seqstate42 tenant b", client_id="tenant_b", limit=3)
    assert first.no_context is False
    assert first.chunks
    assert second.no_context is True
    assert second.chunks == []


def test_dense_skip_reason_missing_api_key(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a")
    _write_active_knowledge(
        clients_root,
        "tenant_a",
        "v1",
        [
            KnowledgeChunk(
                id="c1",
                source_id="s1",
                title="T",
                content="missing key marker misskey33",
                internal_url="uploads/a.txt",
                citation_url=None,
                source_visibility="internal",
            )
        ],
        vectors=[{"chunk_id": "c1", "source_id": "s1", "embedding": [1.0, 0.0, 0.0, 0.0]}],
    )
    outcome = _pipeline(clients_root, embedder=None).retrieve("misskey33", client_id="tenant_a", limit=3)
    assert outcome.dense_skip_reason == "missing_api_key"
    assert outcome.chunks


def test_dense_skip_reason_disabled_by_config(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(
        clients_root,
        "tenant_a",
        extra_config={"retrieval_rules.yaml": "dense:\n  enabled: false\n"},
    )
    _write_active_knowledge(
        clients_root,
        "tenant_a",
        "v1",
        [
            KnowledgeChunk(
                id="c1",
                source_id="s1",
                title="T",
                content="disabled dense marker disdense9",
                internal_url="uploads/a.txt",
                citation_url=None,
                source_visibility="internal",
            )
        ],
        vectors=[{"chunk_id": "c1", "source_id": "s1", "embedding": [1.0, 0.0, 0.0, 0.0]}],
    )
    outcome = _pipeline(clients_root, embedder=MockQueryEmbedder()).retrieve(
        "disdense9",
        client_id="tenant_a",
        limit=3,
    )
    assert outcome.dense_skip_reason == "disabled_by_config"
