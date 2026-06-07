from __future__ import annotations

import logging
from pathlib import Path

import pytest

from packages.config.loaders import save_yaml
from packages.core.config.loader import TenantConfigLoader
from packages.core.config.models import ConfigValidationError
from packages.core.domain.models import ChatRequest, RetrievedChunk
from packages.core.orchestrator.chat_orchestrator import ChatOrchestrator
from packages.core.privacy.config import PrivacyContext, TraceDraft, normalize_privacy
from packages.core.privacy.logging import privacy_safe_log
from packages.core.privacy.processor import gate_trace
from packages.core.privacy.redactor import redact_structure, redact_text
from packages.core.retrieval.models import RetrievalOutcome

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
    base.update(overrides)
    return base


def test_email_redacted() -> None:
    text = redact_text("Write to user@example.com today", detectors=DETECTORS, replacement="[REDACTED]")
    assert "user@example.com" not in text
    assert "[REDACTED]" in text


def test_phone_redacted() -> None:
    text = redact_text("Call +30 6912345678", detectors=DETECTORS, replacement="[REDACTED]")
    assert "6912345678" not in text


def test_credit_card_redacted() -> None:
    text = redact_text("Card 4111111111111111", detectors=DETECTORS, replacement="[REDACTED]")
    assert "4111111111111111" not in text


def test_amka_like_id_redacted() -> None:
    text = redact_text("ID 01015501789 please", detectors=DETECTORS, replacement="[REDACTED]")
    assert "01015501789" not in text


def test_ssn_redacted() -> None:
    text = redact_text("SSN 123-45-6789", detectors=DETECTORS, replacement="[REDACTED]")
    assert "123-45-6789" not in text


def test_iban_redacted() -> None:
    text = redact_text("IBAN GR1601101250000000012300695", detectors=DETECTORS, replacement="[REDACTED]")
    assert "GR1601101250000000012300695" not in text


def test_nested_dict_list_redaction() -> None:
    payload = {
        "history": [{"content": "email me at a@b.co"}],
        "meta": ["plain", "phone 2105551234"],
    }
    redacted = redact_structure(payload, detectors=DETECTORS, replacement="[REDACTED]")
    assert "a@b.co" not in str(redacted)
    assert "2105551234" not in str(redacted)


def test_standard_mode_keeps_allowed_redacted_fields() -> None:
    draft = TraceDraft(
        operational={"mode": "hybrid_local", "retrieved_count": 1},
        input={"original_message": "Reach me at user@example.com"},
        output={"answer": "Thanks user@example.com", "confidence": 0.5},
    )
    gated = gate_trace(
        draft,
        _privacy_cfg(mode="standard"),
        PrivacyContext(client_id="tenant_a", stack_profile="local"),
    )
    assert gated.storable_trace["input"]["original_message"] == "Reach me at [REDACTED]"
    assert "user@example.com" not in gated.storable_trace["output"]["answer"]
    assert "original_message" not in gated.api_trace


def test_anonymized_mode_hashes_user_id() -> None:
    draft = TraceDraft(
        operational={"mode": "hybrid_local"},
        input={"original_message": "hello"},
    )
    gated = gate_trace(
        draft,
        _privacy_cfg(mode="anonymized"),
        PrivacyContext(client_id="tenant_a", user_id="user-123", stack_profile="local"),
    )
    assert "user-123" not in str(gated.storable_trace)
    assert gated.storable_trace.get("user_id_hash")


def test_aggregate_only_drops_message_content() -> None:
    draft = TraceDraft(
        operational={"mode": "hybrid_local", "retrieved_count": 2, "citation_count": 1},
        input={"original_message": "secret query", "history": [{"role": "user", "content": "hi"}]},
        output={"answer": "secret answer", "confidence": 0.8},
    )
    gated = gate_trace(
        draft,
        _privacy_cfg(mode="aggregate_only"),
        PrivacyContext(client_id="tenant_a", stack_profile="local"),
    )
    assert "input" not in gated.storable_trace
    assert "output" not in gated.storable_trace
    assert gated.storable_trace["retrieved_count"] == 2
    assert "secret" not in str(gated.api_trace)


def test_do_not_log_drops_all_content_fields() -> None:
    draft = TraceDraft(
        operational={"mode": "hybrid_local", "no_context": True},
        input={"original_message": "secret"},
        output={"answer": "secret answer"},
    )
    gated = gate_trace(
        draft,
        _privacy_cfg(mode="do_not_log"),
        PrivacyContext(client_id="tenant_a", stack_profile="local"),
    )
    assert "input" not in gated.storable_trace
    assert "output" not in gated.storable_trace
    assert gated.storable_trace["no_context"] is True


def test_invalid_privacy_mode_fails_validation(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    config_dir = clients_root / "tenant_a" / "config"
    config_dir.mkdir(parents=True)
    save_yaml(
        str(config_dir / "client.yaml"),
        {"client_id": "tenant_a", "display_name": "Tenant A", "domain_pack": "generic"},
    )
    save_yaml(str(config_dir / "privacy.yaml"), {"mode": "invalid_mode"})
    with pytest.raises(ConfigValidationError, match="privacy.mode"):
        TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS).load("tenant_a")


def test_do_not_log_forces_raw_message_storage_off() -> None:
    effective = normalize_privacy(_privacy_cfg(mode="do_not_log", storage={"store_raw_messages": True}))
    assert effective.storage["store_raw_messages"] is False


def test_aggregate_only_forces_raw_message_storage_off() -> None:
    effective = normalize_privacy(_privacy_cfg(mode="aggregate_only", storage={"store_raw_messages": True}))
    assert effective.storage["store_raw_messages"] is False


def test_widget_trace_operational_only_by_default(tmp_path: Path) -> None:
    res = _run_orchestrator(
        tmp_path,
        message="Email me at user@example.com",
        privacy=_privacy_cfg(mode="standard"),
    )
    assert res.trace_id.startswith("tr_")
    assert "original_message" not in res.trace
    assert "user@example.com" not in str(res.trace)
    assert res.answer == "Echo answer."


def test_local_debug_trace_only_when_explicitly_enabled(tmp_path: Path) -> None:
    privacy = _privacy_cfg(
        mode="standard",
        ephemeral={"expose_operational_trace": True, "expose_debug_trace_in_api": True},
    )
    res = _run_orchestrator(
        tmp_path,
        message="Email me at user@example.com",
        privacy=privacy,
        stack_profile="local",
    )
    assert res.trace.get("input", {}).get("original_message") == "Email me at [REDACTED]"

    res_firebase = _run_orchestrator(
        tmp_path,
        message="Email me at user@example.com",
        privacy=privacy,
        stack_profile="firebase",
    )
    assert "input" not in res_firebase.trace


def test_privacy_safe_log_removes_content_in_aggregate_only(caplog: pytest.LogCaptureFixture) -> None:
    draft = TraceDraft(
        operational={"mode": "hybrid_local", "retrieved_count": 1},
        input={"original_message": "secret"},
        output={"answer": "secret answer"},
    )
    gated = gate_trace(
        draft,
        _privacy_cfg(mode="aggregate_only"),
        PrivacyContext(client_id="tenant_a", stack_profile="local"),
    )
    with caplog.at_level(logging.INFO):
        privacy_safe_log("chat.completed", gated.log_payload)
    joined = " ".join(caplog.messages)
    assert "secret" not in joined


def test_privacy_safe_log_minimal_for_do_not_log(caplog: pytest.LogCaptureFixture) -> None:
    draft = TraceDraft(operational={"mode": "hybrid_local", "no_context": True})
    gated = gate_trace(
        draft,
        _privacy_cfg(mode="do_not_log"),
        PrivacyContext(client_id="tenant_a", stack_profile="local"),
    )
    with caplog.at_level(logging.INFO):
        privacy_safe_log("chat.completed", gated.log_payload)
    joined = " ".join(caplog.messages)
    assert "chat.completed" in joined
    assert gated.log_payload.get("privacy_mode") == "do_not_log"


def test_no_context_path_passes_privacy_gate(tmp_path: Path) -> None:
    res = _run_orchestrator_no_context(tmp_path, privacy=_privacy_cfg(mode="standard"))
    assert res.trace.get("no_context") is True
    assert res.trace_id.startswith("tr_")


def test_crisis_path_passes_privacy_gate(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, privacy=_privacy_cfg(mode="standard"))
    save_yaml(
        str(clients_root / "tenant_a" / "config" / "crisis_rules.yaml"),
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
    orchestrator = _build_orchestrator(clients_root)
    res = orchestrator.answer(
        ChatRequest(client_id="tenant_a", message="CRISIS_TEST_TRIGGER", top_k=3)
    )
    assert res.trace.get("crisis_hit") is True
    assert res.trace_id.startswith("tr_")


def test_fallback_path_passes_privacy_gate(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, privacy=_privacy_cfg(mode="standard"))
    save_yaml(str(clients_root / "tenant_a" / "config" / "llm.yaml"), {"blocked_content": {"fallback_message": "Fallback."}})

    class _Retriever:
        def retrieve_with_outcome(self, query, limit=5, mode="hybrid_local", **kwargs):
            return RetrievalOutcome(chunks=[_chunk()], no_context=False)

    from packages.adapters.llm.resilient_provider import ResilientLLMProvider
    from packages.core.llm.key_pool import LLMKeyPool
    from packages.core.llm.orchestrator import LLMOrchestrator
    from packages.adapters.llm.gemini_adapter import GeminiLLMBackend
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
    )
    res = orchestrator.answer(ChatRequest(client_id="tenant_a", message="hello", top_k=3))
    assert res.trace.get("fallback_used") is True
    assert res.trace.get("llm_skipped_citation_pipeline") is True


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        id="c1",
        text="Doc\nbody",
        source="uploads/a.txt",
        score=0.9,
        metadata={"title": "Doc", "internal_url": "uploads/a.txt", "source_visibility": "internal"},
    )


class _MockPolicy:
    def build_system_prompt(self, client_id: str, mode: str) -> str:
        return "system"


class _MockLLM:
    def generate_with_outcome(self, system_prompt, messages, *, llm_config=None):
        from packages.core.llm.models import LLMOutcome

        return LLMOutcome(text="Echo answer.", model_used="test")

    def generate(self, system_prompt, messages, model, temperature=0.2) -> str:
        return "Echo answer."


class _NoContextRetriever:
    def retrieve_with_outcome(self, query, limit=5, mode="hybrid_local", **kwargs):
        return RetrievalOutcome(chunks=[], no_context=True, no_context_message="No relevant sources.")


def _write_client(clients_root: Path, *, privacy: dict | None = None) -> None:
    config_dir = clients_root / "tenant_a" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    save_yaml(
        str(config_dir / "client.yaml"),
        {"client_id": "tenant_a", "display_name": "Tenant A", "domain_pack": "generic"},
    )
    if privacy is not None:
        save_yaml(str(config_dir / "privacy.yaml"), privacy)


def _build_orchestrator(clients_root: Path, *, stack_profile: str = "local") -> ChatOrchestrator:
    return ChatOrchestrator(
        llm_provider=_MockLLM(),
        retriever=_NoContextRetriever(),
        prompt_policy=_MockPolicy(),
        config_loader=TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS),
        stack_profile=stack_profile,
    )


def _run_orchestrator(
    tmp_path: Path,
    *,
    message: str,
    privacy: dict,
    stack_profile: str = "local",
):
    clients_root = tmp_path / "clients"
    _write_client(clients_root, privacy=privacy)

    class _Retriever:
        def retrieve_with_outcome(self, query, limit=5, mode="hybrid_local", **kwargs):
            return RetrievalOutcome(chunks=[_chunk()], no_context=False)

    orchestrator = ChatOrchestrator(
        llm_provider=_MockLLM(),
        retriever=_Retriever(),
        prompt_policy=_MockPolicy(),
        config_loader=TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS),
        stack_profile=stack_profile,
    )
    return orchestrator.answer(ChatRequest(client_id="tenant_a", message=message, top_k=3))


def _run_orchestrator_no_context(tmp_path: Path, *, privacy: dict):
    clients_root = tmp_path / "clients"
    _write_client(clients_root, privacy=privacy)
    return _build_orchestrator(clients_root).answer(
        ChatRequest(client_id="tenant_a", message="hello", top_k=3)
    )
