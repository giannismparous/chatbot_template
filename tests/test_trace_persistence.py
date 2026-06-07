from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.dependencies import stack as stack_module
from packages.adapters.metrics.local_sqlite_metrics_store import LocalSqliteMetricsStore
from packages.adapters.traces.local_sqlite_trace_store import LocalSqliteTraceStore
from packages.config.loaders import save_yaml
from packages.core.config.loader import TenantConfigLoader
from packages.core.domain.models import ChatRequest, RetrievedChunk
from packages.core.orchestrator.chat_orchestrator import ChatOrchestrator
from packages.core.privacy.config import PrivacyContext, TraceDraft
from packages.core.privacy.processor import gate_trace
from packages.core.retrieval.models import RetrievalOutcome
from packages.core.traces.models import TraceRecord

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"
DETECTORS = {
    "email": True,
    "phone": True,
    "credit_card": True,
    "amka": True,
    "ssn": True,
    "iban": True,
    "address_heuristic": False,
}


def _privacy_cfg(**overrides) -> dict:
    base = {
        "mode": "standard",
        "storage": {
            "persist_traces": False,
            "store_raw_messages": True,
            "store_rewritten_query": True,
            "store_answer": True,
            "store_history": True,
            "store_retrieval_detail": True,
            "store_llm_detail": True,
        },
        "pii": {
            "redaction_enabled": True,
            "replacement": "[REDACTED]",
            "detectors": DETECTORS,
        },
        "ephemeral": {"expose_operational_trace": True, "expose_debug_trace_in_api": False},
    }
    if "storage" in overrides:
        base["storage"] = {**base["storage"], **overrides.pop("storage")}
    base.update(overrides)
    return base


def _stores(db_path: Path) -> tuple[LocalSqliteTraceStore, LocalSqliteMetricsStore]:
    return LocalSqliteTraceStore(db_path), LocalSqliteMetricsStore(db_path)


def _write_client(clients_root: Path, *, privacy: dict | None = None, client_id: str = "tenant_a") -> None:
    config_dir = clients_root / client_id / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    save_yaml(
        str(config_dir / "client.yaml"),
        {"client_id": client_id, "display_name": client_id, "domain_pack": "generic"},
    )
    if privacy is not None:
        save_yaml(str(config_dir / "privacy.yaml"), privacy)


class _MockPolicy:
    def build_system_prompt(self, client_id: str, mode: str) -> str:
        return "system"


class _MockLLM:
    def generate_with_outcome(self, system_prompt, messages, *, llm_config=None):
        from packages.core.llm.models import LLMOutcome

        return LLMOutcome(text="Echo answer.", model_used="test")


class _Retriever:
    def retrieve_with_outcome(self, query, limit=5, mode="hybrid_local", **kwargs):
        return RetrievalOutcome(
            chunks=[
                RetrievedChunk(
                    id="c1",
                    text="Doc body",
                    source="uploads/a.txt",
                    score=0.9,
                    metadata={"title": "Doc", "internal_url": "uploads/a.txt"},
                )
            ],
            no_context=False,
        )


def _orchestrator(
    clients_root: Path,
    db_path: Path,
    *,
    privacy: dict,
    client_id: str = "tenant_a",
) -> ChatOrchestrator:
    trace_store, metrics_store = _stores(db_path)
    return ChatOrchestrator(
        llm_provider=_MockLLM(),
        retriever=_Retriever(),
        prompt_policy=_MockPolicy(),
        config_loader=TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS),
        stack_profile="local",
        trace_store=trace_store,
        metrics_store=metrics_store,
    )


def test_standard_persist_traces_true_stores_redacted_content(tmp_path: Path) -> None:
    db_path = tmp_path / "traces.sqlite3"
    clients_root = tmp_path / "clients"
    privacy = _privacy_cfg(storage={"persist_traces": True})
    _write_client(clients_root, privacy=privacy)
    orchestrator = _orchestrator(clients_root, db_path, privacy=privacy)
    res = orchestrator.answer(
        ChatRequest(client_id="tenant_a", message="Email me at user@example.com", top_k=3)
    )
    record = LocalSqliteTraceStore(db_path).get(res.trace_id, client_id="tenant_a")
    assert record is not None
    assert "user@example.com" not in json.dumps(record.payload)
    assert record.payload["input"]["original_message"] == "Email me at [REDACTED]"


def test_persist_traces_false_skips_row_but_metrics_update(tmp_path: Path) -> None:
    db_path = tmp_path / "traces.sqlite3"
    clients_root = tmp_path / "clients"
    privacy = _privacy_cfg(storage={"persist_traces": False})
    _write_client(clients_root, privacy=privacy)
    orchestrator = _orchestrator(clients_root, db_path, privacy=privacy)
    res = orchestrator.answer(ChatRequest(client_id="tenant_a", message="hello", top_k=3))
    assert LocalSqliteTraceStore(db_path).get(res.trace_id) is None
    metrics = LocalSqliteMetricsStore(db_path).get_client_metrics("tenant_a")
    assert metrics.total_chats == 1


def test_do_not_log_writes_no_trace_row_but_metrics_update(tmp_path: Path) -> None:
    db_path = tmp_path / "traces.sqlite3"
    clients_root = tmp_path / "clients"
    privacy = _privacy_cfg(mode="do_not_log", storage={"persist_traces": True})
    _write_client(clients_root, privacy=privacy)
    orchestrator = _orchestrator(clients_root, db_path, privacy=privacy)
    res = orchestrator.answer(ChatRequest(client_id="tenant_a", message="hello", top_k=3))
    assert LocalSqliteTraceStore(db_path).get(res.trace_id) is None
    metrics = LocalSqliteMetricsStore(db_path).get_client_metrics("tenant_a")
    assert metrics.total_chats == 1


def test_aggregate_only_row_contains_only_aggregate_safe_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "traces.sqlite3"
    clients_root = tmp_path / "clients"
    privacy = _privacy_cfg(mode="aggregate_only", storage={"persist_traces": True})
    _write_client(clients_root, privacy=privacy)
    orchestrator = _orchestrator(clients_root, db_path, privacy=privacy)
    res = orchestrator.answer(ChatRequest(client_id="tenant_a", message="secret query", top_k=3))
    record = LocalSqliteTraceStore(db_path).get(res.trace_id)
    assert record is not None
    payload = record.payload
    assert "input" not in payload
    assert "output" not in payload
    assert "retrieval" not in payload
    assert "secret" not in json.dumps(payload)
    assert payload.get("retrieved_count") == 1


def test_never_persists_trace_draft(tmp_path: Path) -> None:
    db_path = tmp_path / "traces.sqlite3"
    store = LocalSqliteTraceStore(db_path)
    draft = TraceDraft(
        operational={"mode": "hybrid_local"},
        input={"original_message": "raw draft message"},
    )
    gated = gate_trace(
        draft,
        _privacy_cfg(storage={"persist_traces": True}),
        PrivacyContext(client_id="tenant_a"),
    )
    record = TraceRecord.from_gated(gated=gated, context=PrivacyContext(client_id="tenant_a"))
    store.save(record)
    with pytest.raises(TypeError):
        store.save({"trace_id": "tr_bad"})  # type: ignore[arg-type]


def test_admin_get_success_with_admin_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "traces.sqlite3"
    clients_root = tmp_path / "clients"
    privacy = _privacy_cfg(storage={"persist_traces": True})
    _write_client(clients_root, privacy=privacy)
    orchestrator = _orchestrator(clients_root, db_path, privacy=privacy)
    res = orchestrator.answer(ChatRequest(client_id="tenant_a", message="hello", top_k=3))

    monkeypatch.setenv("TRACES_SQLITE_PATH", str(db_path))
    stack_module.reset_stack()

    from apps.api.main import app

    client = TestClient(app)
    response = client.get(
        f"/v1/admin/traces/{res.trace_id}",
        headers={"x-admin-token": "test-admin-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["trace_id"] == res.trace_id
    assert body["client_id"] == "tenant_a"


def test_admin_get_401_without_admin_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRACES_SQLITE_PATH", str(tmp_path / "traces.sqlite3"))
    stack_module.reset_stack()
    from apps.api.main import app

    client = TestClient(app)
    response = client.get("/v1/admin/traces/tr_missing")
    assert response.status_code == 401


def test_widget_key_cannot_access_admin_trace_endpoint(client: TestClient) -> None:
    res = client.get(
        "/v1/admin/traces/tr_missing",
        headers={"x-client-key": "wk_test_tenant_a", "Origin": "http://testserver"},
    )
    assert res.status_code == 401


def test_client_id_mismatch_query_returns_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "traces.sqlite3"
    clients_root = tmp_path / "clients"
    privacy = _privacy_cfg(storage={"persist_traces": True})
    _write_client(clients_root, privacy=privacy)
    orchestrator = _orchestrator(clients_root, db_path, privacy=privacy)
    res = orchestrator.answer(ChatRequest(client_id="tenant_a", message="hello", top_k=3))

    monkeypatch.setenv("TRACES_SQLITE_PATH", str(db_path))
    stack_module.reset_stack()
    from apps.api.main import app

    client = TestClient(app)
    response = client.get(
        f"/v1/admin/traces/{res.trace_id}?client_id=tenant_b",
        headers={"x-admin-token": "test-admin-token"},
    )
    assert response.status_code == 404


def test_persist_traces_false_admin_get_returns_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "traces.sqlite3"
    clients_root = tmp_path / "clients"
    privacy = _privacy_cfg(storage={"persist_traces": False})
    _write_client(clients_root, privacy=privacy)
    orchestrator = _orchestrator(clients_root, db_path, privacy=privacy)
    res = orchestrator.answer(ChatRequest(client_id="tenant_a", message="hello", top_k=3))
    assert res.trace_id.startswith("tr_")

    monkeypatch.setenv("TRACES_SQLITE_PATH", str(db_path))
    stack_module.reset_stack()
    from apps.api.main import app

    client = TestClient(app)
    response = client.get(
        f"/v1/admin/traces/{res.trace_id}",
        headers={"x-admin-token": "test-admin-token"},
    )
    assert response.status_code == 404
