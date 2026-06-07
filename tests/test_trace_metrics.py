from __future__ import annotations

from pathlib import Path

import pytest

from packages.adapters.metrics.local_sqlite_metrics_store import LocalSqliteMetricsStore
from packages.adapters.traces.local_sqlite_trace_store import LocalSqliteTraceStore
from packages.config.loaders import save_yaml
from packages.core.config.loader import TenantConfigLoader
from packages.core.domain.models import ChatRequest, RetrievedChunk
from packages.core.orchestrator.chat_orchestrator import ChatOrchestrator
from packages.core.privacy.config import PrivacyContext, TraceDraft
from packages.core.privacy.processor import gate_trace
from packages.core.retrieval.models import RetrievalOutcome
from packages.core.traces.metrics_extractor import extract_metric_deltas

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"


def _privacy_cfg(**overrides) -> dict:
    base = {
        "mode": "standard",
        "storage": {"persist_traces": False},
        "pii": {"redaction_enabled": True, "replacement": "[REDACTED]"},
    }
    if "storage" in overrides:
        base["storage"] = {**base.get("storage", {}), **overrides.pop("storage")}
    base.update(overrides)
    return base


def _write_client(
    clients_root: Path,
    *,
    privacy: dict,
    crisis: bool = False,
    off_topic_guard: bool = False,
) -> None:
    config_dir = clients_root / "tenant_a" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    save_yaml(
        str(config_dir / "client.yaml"),
        {"client_id": "tenant_a", "display_name": "Tenant A", "domain_pack": "generic"},
    )
    save_yaml(str(config_dir / "privacy.yaml"), privacy)
    if crisis:
        save_yaml(
            str(config_dir / "crisis_rules.yaml"),
            {
                "enabled": True,
                "categories": [
                    {
                        "id": "test_crisis",
                        "match": {"any_keywords": ["CRISIS_TEST_TRIGGER"]},
                        "response": {"message": "Crisis response."},
                    }
                ],
            },
        )
    if off_topic_guard:
        save_yaml(
            str(config_dir / "guardrails.yaml"),
            {
                "enabled": True,
                "input_guard": {
                    "enabled": True,
                    "off_topic": {
                        "enabled": True,
                        "allowed_topic_keywords": ["allowedtopic"],
                        "block_message": "Off-topic blocked.",
                    },
                },
            },
        )


class _MockPolicy:
    def build_system_prompt(self, client_id: str, mode: str) -> str:
        return "system"


class _NoContextRetriever:
    def retrieve_with_outcome(self, query, limit=5, mode="hybrid_local", **kwargs):
        return RetrievalOutcome(chunks=[], no_context=True, no_context_message="No sources.")


class _Retriever:
    def retrieve_with_outcome(self, query, limit=5, mode="hybrid_local", **kwargs):
        return RetrievalOutcome(
            chunks=[
                RetrievedChunk(
                    id="c1",
                    text="Doc",
                    source="uploads/a.txt",
                    score=0.85,
                    metadata={"title": "Doc"},
                )
            ],
            no_context=False,
        )


class _MockLLM:
    def generate_with_outcome(self, system_prompt, messages, *, llm_config=None):
        from packages.core.llm.models import LLMOutcome

        return LLMOutcome(text="Echo answer.", model_used="test")


def _orchestrator(clients_root: Path, db_path: Path) -> ChatOrchestrator:
    return ChatOrchestrator(
        llm_provider=_MockLLM(),
        retriever=_Retriever(),
        prompt_policy=_MockPolicy(),
        config_loader=TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS),
        stack_profile="local",
        trace_store=LocalSqliteTraceStore(db_path),
        metrics_store=LocalSqliteMetricsStore(db_path),
    )


def test_metrics_total_and_no_context(tmp_path: Path) -> None:
    db_path = tmp_path / "traces.sqlite3"
    clients_root = tmp_path / "clients"
    _write_client(clients_root, privacy=_privacy_cfg())
    orchestrator = ChatOrchestrator(
        llm_provider=_MockLLM(),
        retriever=_NoContextRetriever(),
        prompt_policy=_MockPolicy(),
        config_loader=TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS),
        stack_profile="local",
        trace_store=LocalSqliteTraceStore(db_path),
        metrics_store=LocalSqliteMetricsStore(db_path),
    )
    orchestrator.answer(ChatRequest(client_id="tenant_a", message="hello", top_k=3))
    metrics = LocalSqliteMetricsStore(db_path).get_client_metrics("tenant_a")
    assert metrics.total_chats == 1
    assert metrics.no_context == 1


def test_metrics_crisis_counter(tmp_path: Path) -> None:
    db_path = tmp_path / "traces.sqlite3"
    clients_root = tmp_path / "clients"
    _write_client(clients_root, privacy=_privacy_cfg(), crisis=True)
    orchestrator = _orchestrator(clients_root, db_path)
    orchestrator.answer(ChatRequest(client_id="tenant_a", message="CRISIS_TEST_TRIGGER", top_k=3))
    metrics = LocalSqliteMetricsStore(db_path).get_client_metrics("tenant_a")
    assert metrics.crisis == 1


def test_metrics_input_blocked_counter(tmp_path: Path) -> None:
    db_path = tmp_path / "traces.sqlite3"
    clients_root = tmp_path / "clients"
    _write_client(clients_root, privacy=_privacy_cfg(), off_topic_guard=True)
    orchestrator = ChatOrchestrator(
        llm_provider=_MockLLM(),
        retriever=_NoContextRetriever(),
        prompt_policy=_MockPolicy(),
        config_loader=TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS),
        stack_profile="local",
        trace_store=LocalSqliteTraceStore(db_path),
        metrics_store=LocalSqliteMetricsStore(db_path),
    )
    orchestrator.answer(ChatRequest(client_id="tenant_a", message="astronomy question", top_k=3))
    metrics = LocalSqliteMetricsStore(db_path).get_client_metrics("tenant_a")
    assert metrics.input_blocked == 1


def test_metrics_provider_fallback_counter(tmp_path: Path) -> None:
    db_path = tmp_path / "traces.sqlite3"
    clients_root = tmp_path / "clients"
    _write_client(clients_root, privacy=_privacy_cfg())
    save_yaml(str(clients_root / "tenant_a" / "config" / "llm.yaml"), {"blocked_content": {"fallback_message": "Fallback."}})

    from packages.adapters.llm.gemini_adapter import GeminiLLMBackend
    from packages.adapters.llm.resilient_provider import ResilientLLMProvider
    from packages.core.llm.key_pool import LLMKeyPool
    from packages.core.llm.orchestrator import LLMOrchestrator
    from packages.core.ports.llm_backend import LLMGenerateResult

    def _blocked(**kwargs):
        return LLMGenerateResult(text="", blocked=True, block_reason="SAFETY")

    llm = ResilientLLMProvider(
        LLMOrchestrator(
            backend=GeminiLLMBackend(generate_fn=_blocked),
            key_pool=LLMKeyPool(keys=["k1"]),
            stack_profile="local",
        )
    )
    orchestrator = ChatOrchestrator(
        llm_provider=llm,
        retriever=_Retriever(),
        prompt_policy=_MockPolicy(),
        config_loader=TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS),
        stack_profile="local",
        trace_store=LocalSqliteTraceStore(db_path),
        metrics_store=LocalSqliteMetricsStore(db_path),
    )
    orchestrator.answer(ChatRequest(client_id="tenant_a", message="hello", top_k=3))
    metrics = LocalSqliteMetricsStore(db_path).get_client_metrics("tenant_a")
    assert metrics.provider_fallback == 1


def test_confidence_bucket_updates(tmp_path: Path) -> None:
    db_path = tmp_path / "traces.sqlite3"
    clients_root = tmp_path / "clients"
    _write_client(clients_root, privacy=_privacy_cfg())
    _orchestrator(clients_root, db_path).answer(
        ChatRequest(client_id="tenant_a", message="hello", top_k=3)
    )
    metrics = LocalSqliteMetricsStore(db_path).get_client_metrics("tenant_a")
    assert sum(metrics.confidence_buckets.values()) == 1
    assert metrics.confidence_buckets["0.8-1.0"] == 1


def test_latency_sum_and_count_update(tmp_path: Path) -> None:
    db_path = tmp_path / "traces.sqlite3"
    clients_root = tmp_path / "clients"
    _write_client(clients_root, privacy=_privacy_cfg())
    _orchestrator(clients_root, db_path).answer(
        ChatRequest(client_id="tenant_a", message="hello", top_k=3)
    )
    metrics = LocalSqliteMetricsStore(db_path).get_client_metrics("tenant_a")
    assert metrics.latency_ms_count == 1
    assert metrics.latency_ms_sum >= 0


def test_metrics_extractor_ignores_unsafe_fields() -> None:
    draft = TraceDraft(
        operational={"mode": "hybrid_local", "crisis_hit": True},
        input={"original_message": "secret message"},
        output={"answer": "secret answer", "confidence": 0.9},
        retrieval={"selected": [{"text": "chunk body", "url": "https://internal/doc"}]},
    )
    gated = gate_trace(
        draft,
        _privacy_cfg(mode="standard", storage={"persist_traces": True, "store_raw_messages": True}),
        PrivacyContext(client_id="tenant_a"),
    )
    deltas = extract_metric_deltas(gated.storable_trace)
    assert deltas.crisis == 1
    assert deltas.confidence_buckets.get("0.8-1.0") == 1
    assert "secret" not in str(deltas)


def test_metrics_extractor_ignores_nested_output_confidence_without_top_level() -> None:
    storable = {
        "output": {"confidence": 0.75, "answer": "secret"},
        "crisis_hit": False,
    }
    deltas = extract_metric_deltas(storable)
    assert deltas.confidence_buckets == {}
    assert "secret" not in str(deltas)


def test_persist_traces_false_still_updates_metrics(tmp_path: Path) -> None:
    db_path = tmp_path / "traces.sqlite3"
    clients_root = tmp_path / "clients"
    _write_client(clients_root, privacy=_privacy_cfg(storage={"persist_traces": False}))
    _orchestrator(clients_root, db_path).answer(
        ChatRequest(client_id="tenant_a", message="hello", top_k=3)
    )
    metrics = LocalSqliteMetricsStore(db_path).get_client_metrics("tenant_a")
    assert metrics.total_chats == 1
