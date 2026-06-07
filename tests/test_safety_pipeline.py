from __future__ import annotations

from pathlib import Path

import pytest

from packages.config.loaders import save_yaml
from packages.core.citations.context_builder import build_citation_context
from packages.core.citations.enforcer import enforce_citations
from packages.core.config.loader import TenantConfigLoader
from packages.core.config.models import ConfigValidationError
from packages.core.domain.models import ChatRequest, RetrievedChunk
from packages.core.orchestrator.chat_orchestrator import ChatOrchestrator
from packages.core.retrieval.models import RetrievalOutcome
from packages.core.safety.config import apply_regulated_overrides
from packages.core.safety.crisis_filter import check_crisis
from packages.core.safety.disclaimer_injector import inject_disclaimers
from packages.core.safety.input_guard import check_input_guard
from packages.core.safety.regulated_citation import enforce_regulated_citations
from packages.core.safety.unsafe_output_sanitizer import sanitize_output

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"

CRISIS_TRIGGER = "CRISIS_TEST_TRIGGER"
CRISIS_MESSAGE = "Configured crisis safety response."
JAILBREAK_TRIGGER = "JAILBREAK_TEST_PATTERN_XYZ"
OFF_TOPIC_ALLOWED = "billing hours"


def _write_client(
    clients_root: Path,
    client_id: str = "tenant_a",
    *,
    regulated: bool = False,
    crisis_rules: dict | None = None,
    guardrails: dict | None = None,
    disclaimers: dict | None = None,
    escalation_rules: dict | None = None,
    source_whitelist: dict | None = None,
) -> Path:
    config_dir = clients_root / client_id / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    client_data = {
        "client_id": client_id,
        "display_name": "Safety Test Client",
        "domain_pack": "generic",
    }
    if regulated:
        client_data["regulated_mode"] = True
    save_yaml(str(config_dir / "client.yaml"), client_data)
    if crisis_rules is not None:
        save_yaml(str(config_dir / "crisis_rules.yaml"), crisis_rules)
    if guardrails is not None:
        save_yaml(str(config_dir / "guardrails.yaml"), guardrails)
    if disclaimers is not None:
        save_yaml(str(config_dir / "disclaimers.yaml"), disclaimers)
    if escalation_rules is not None:
        save_yaml(str(config_dir / "escalation_rules.yaml"), escalation_rules)
    if source_whitelist is not None:
        save_yaml(str(config_dir / "source_whitelist.yaml"), source_whitelist)
    return config_dir


def _loader(clients_root: Path) -> TenantConfigLoader:
    return TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)


def _sample_crisis_rules(*, enabled: bool = True, with_exclusion: bool = False) -> dict:
    rules = {
        "enabled": enabled,
        "categories": [
            {
                "id": "test_crisis",
                "priority": 100,
                "enabled": True,
                "match": {
                    "any_keywords": [CRISIS_TRIGGER],
                    "min_keyword_hits": 1,
                },
                "response": {"message": CRISIS_MESSAGE},
                "hotlines": [{"label": "Fixture Hotline", "number": "9999"}],
                "flags": {"requires_human": True},
            }
        ],
        "exclusions": {
            "any_keywords": ["academic policy"] if with_exclusion else [],
        },
        "hotline_format": "{label}: {number}",
    }
    return rules


def _chunk(**kwargs) -> RetrievedChunk:
    defaults = {
        "chunk_id": "c1",
        "title": "Doc",
        "content": "Support hours are nine to five.",
        "internal_url": "uploads/private.txt",
        "citation_url": None,
        "source_visibility": "internal",
    }
    defaults.update(kwargs)
    return RetrievedChunk(
        id=defaults["chunk_id"],
        text=f"{defaults['title']}\n{defaults['content']}",
        source=defaults["internal_url"],
        score=0.9,
        metadata={
            "title": defaults["title"],
            "internal_url": defaults["internal_url"],
            "citation_url": defaults.get("citation_url"),
            "source_visibility": defaults["source_visibility"],
        },
    )


class _MockLLM:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.called = False

    def generate(self, system_prompt, messages, model, temperature=0.2) -> str:
        self.called = True
        return self.answer


class _MockPolicy:
    def build_system_prompt(self, client_id: str, mode: str) -> str:
        return "system"


class _TrackingRetriever:
    def __init__(self, outcome: RetrievalOutcome) -> None:
        self.outcome = outcome
        self.called = False

    def retrieve_with_outcome(self, query, limit=5, mode="hybrid_local", **kwargs):
        self.called = True
        return self.outcome


def test_crisis_hit_returns_configured_message(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, crisis_rules=_sample_crisis_rules())
    merged = _loader(clients_root).load("tenant_a")
    effective = apply_regulated_overrides(merged)
    block = check_crisis(f"I need help {CRISIS_TRIGGER}", effective)
    assert block is not None
    assert CRISIS_MESSAGE in block.answer
    assert "Fixture Hotline: 9999" in block.answer


def test_crisis_hit_bypasses_retriever_and_llm(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, crisis_rules=_sample_crisis_rules())
    retriever = _TrackingRetriever(
        RetrievalOutcome(chunks=[_chunk()], no_context=False)
    )
    llm = _MockLLM("should not run")
    orchestrator = ChatOrchestrator(
        llm_provider=llm,
        retriever=retriever,
        prompt_policy=_MockPolicy(),
        default_model="test",
        config_loader=_loader(clients_root),
    )
    res = orchestrator.answer(
        ChatRequest(client_id="tenant_a", message=f"help {CRISIS_TRIGGER}", top_k=3)
    )
    assert CRISIS_MESSAGE in res.answer
    assert retriever.called is False
    assert llm.called is False
    assert res.requires_human is True
    assert res.escalation is not None
    assert res.escalation.type == "crisis"


def test_crisis_exclusion_prevents_false_positive(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, crisis_rules=_sample_crisis_rules(with_exclusion=True))
    merged = _loader(clients_root).load("tenant_a")
    effective = apply_regulated_overrides(merged)
    block = check_crisis(f"academic policy {CRISIS_TRIGGER}", effective)
    assert block is None


def test_crisis_cannot_be_disabled_in_regulated_mode(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(
        clients_root,
        regulated=True,
        crisis_rules=_sample_crisis_rules(enabled=False),
    )
    merged = _loader(clients_root).load("tenant_a")
    effective = apply_regulated_overrides(merged)
    assert effective.crisis_rules["enabled"] is True
    block = check_crisis(CRISIS_TRIGGER, effective)
    assert block is not None


def test_no_hardcoded_healthcare_greek_hotline_literals_in_core_safety() -> None:
    safety_dir = ROOT / "packages" / "core" / "safety"
    forbidden = ["1018", "9999", "Γραμμή", "αυτοκτον", "suicide", "self-harm"]
    for path in safety_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{token!r} found in {path.name}"


def test_jailbreak_blocks_before_retrieval_and_llm(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(
        clients_root,
        guardrails={
            "enabled": True,
            "input_guard": {
                "enabled": True,
                "jailbreak": {
                    "any_keywords": [JAILBREAK_TRIGGER],
                    "block_message": "Blocked jailbreak attempt.",
                },
            },
        },
    )
    retriever = _TrackingRetriever(RetrievalOutcome(chunks=[_chunk()], no_context=False))
    llm = _MockLLM("should not run")
    orchestrator = ChatOrchestrator(
        llm_provider=llm,
        retriever=retriever,
        prompt_policy=_MockPolicy(),
        default_model="test",
        config_loader=_loader(clients_root),
    )
    res = orchestrator.answer(
        ChatRequest(client_id="tenant_a", message=JAILBREAK_TRIGGER, top_k=3)
    )
    assert "Blocked jailbreak" in res.answer
    assert retriever.called is False
    assert llm.called is False
    assert res.escalation is not None
    assert res.escalation.type == "input_blocked"


def test_off_topic_disabled_by_default(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root)
    merged = _loader(clients_root).load("tenant_a")
    effective = apply_regulated_overrides(merged)
    block = check_input_guard("completely unrelated astronomy topic", effective)
    assert block is None


def test_off_topic_blocks_only_when_enabled(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(
        clients_root,
        guardrails={
            "enabled": True,
            "input_guard": {
                "enabled": True,
                "off_topic": {
                    "enabled": True,
                    "allowed_topic_keywords": [OFF_TOPIC_ALLOWED],
                    "block_message": "Off-topic blocked.",
                },
            },
        },
    )
    merged = _loader(clients_root).load("tenant_a")
    effective = apply_regulated_overrides(merged)
    assert check_input_guard("astronomy question", effective) is not None
    assert check_input_guard(f"question about {OFF_TOPIC_ALLOWED}", effective) is None


def test_regulated_mode_forces_citation_whitelist_settings(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(
        clients_root,
        regulated=True,
        crisis_rules={"enabled": False, "categories": []},
        source_whitelist={
            "allowed_public_domains": [],
            "citation_url_rules": {"allow_only_whitelisted": False},
            "citation_enforcement": {"require_citation_markers": False},
        },
    )
    merged = _loader(clients_root).load("tenant_a")
    effective = apply_regulated_overrides(merged)
    assert effective.crisis_rules["enabled"] is True
    assert effective.source_whitelist["show_public_sources_only"] is True
    assert effective.source_whitelist["citation_url_rules"]["allow_only_whitelisted"] is True
    assert effective.source_whitelist["citation_enforcement"]["require_citation_markers"] is True


def test_regulated_uncited_factual_sentence_rephrased(tmp_path: Path) -> None:
    ctx = build_citation_context([_chunk()])
    guardrails = {
        "regulated_profile": {
            "require_claim_level_citations": True,
            "block_on_claim_validation_fail": False,
            "refusal_phrase": "not found in approved sources",
            "factual_keywords": ["hours"],
        }
    }
    result = enforce_regulated_citations(
        "Support hours are nine to five.",
        ctx,
        guardrails,
        compiled_factual_patterns=[],
        compiled_exempt_patterns=[],
    )
    assert "not found in approved sources" in result.answer
    assert result.hard_refused is False


def test_regulated_valid_inline_citation_preserved() -> None:
    ctx = build_citation_context([_chunk()])
    guardrails = {
        "regulated_profile": {
            "require_claim_level_citations": True,
            "block_on_claim_validation_fail": False,
            "refusal_phrase": "not found in approved sources",
            "factual_keywords": ["hours"],
        }
    }
    result = enforce_regulated_citations(
        "Support hours are nine to five [1].",
        ctx,
        guardrails,
        compiled_factual_patterns=[],
        compiled_exempt_patterns=[],
    )
    assert "[1]" in result.answer
    assert result.claim_failures == []


def test_regulated_end_of_paragraph_citation_blob_rejected() -> None:
    ctx = build_citation_context(
        [
            _chunk(chunk_id="c1"),
            _chunk(chunk_id="c2", title="Second", content="Another fact here."),
        ]
    )
    guardrails = {
        "regulated_profile": {
            "require_claim_level_citations": True,
            "block_on_claim_validation_fail": False,
            "refusal_phrase": "not found in approved sources",
            "end_of_paragraph_citations_invalid": True,
            "factual_keywords": ["hours", "fact"],
        }
    }
    result = enforce_regulated_citations(
        "Support hours are nine to five. Another fact here. [1]",
        ctx,
        guardrails,
        compiled_factual_patterns=[],
        compiled_exempt_patterns=[],
    )
    assert "not found in approved sources" in result.answer
    assert result.claim_failures


def test_standard_mode_skips_claim_level_validator_in_orchestrator(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, regulated=False)
    llm = _MockLLM("Support hours are nine to five without citation.")

    class _Retriever:
        def retrieve_with_outcome(self, query, limit=5, mode="hybrid_local", **kwargs):
            return RetrievalOutcome(chunks=[_chunk()], no_context=False)

    orchestrator = ChatOrchestrator(
        llm_provider=llm,
        retriever=_Retriever(),
        prompt_policy=_MockPolicy(),
        default_model="test",
        config_loader=_loader(clients_root),
    )
    res = orchestrator.answer(ChatRequest(client_id="tenant_a", message="hours?", top_k=3))
    assert res.trace.get("claim_failures") is None or res.trace.get("claim_failures") == []
    assert "without citation" in res.answer


def test_disclaimer_appended_in_regulated_mode(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(
        clients_root,
        regulated=True,
        disclaimers={
            "enabled": True,
            "items": [
                {
                    "id": "footer",
                    "enabled": True,
                    "placement": "footer",
                    "when": {"regulated_mode_only": True, "any_answer": True},
                    "text": "Regulated disclaimer footer.",
                }
            ],
        },
    )
    answer, ids = inject_disclaimers(
        "Answer body.",
        {
            "enabled": True,
            "items": [
                {
                    "id": "footer",
                    "enabled": True,
                    "placement": "footer",
                    "when": {"regulated_mode_only": True, "any_answer": True},
                    "text": "Regulated disclaimer footer.",
                }
            ],
        },
        regulated_mode=True,
        locale={"primary_language": "en"},
    )
    assert "Regulated disclaimer footer." in answer
    assert ids == ["footer"]


def test_disclaimer_dedup_works() -> None:
    answer, ids = inject_disclaimers(
        "Answer.\n\nRegulated disclaimer footer.",
        {
            "enabled": True,
            "items": [
                {
                    "id": "footer",
                    "enabled": True,
                    "placement": "footer",
                    "dedupe": True,
                    "when": {"any_answer": True},
                    "text": "Regulated disclaimer footer.",
                }
            ],
        },
        regulated_mode=True,
        locale={"primary_language": "en"},
    )
    assert answer.count("Regulated disclaimer footer.") == 1
    assert ids == []


def test_disclaimer_skipped_on_crisis_path() -> None:
    answer, ids = inject_disclaimers(
        "Crisis response.",
        {
            "enabled": True,
            "items": [
                {
                    "id": "footer",
                    "enabled": True,
                    "when": {"any_answer": True},
                    "text": "Should not appear.",
                }
            ],
        },
        regulated_mode=True,
        locale={"primary_language": "en"},
        crisis_path=True,
    )
    assert answer == "Crisis response."
    assert ids == []


def test_output_sanitizer_strips_configured_patterns(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(
        clients_root,
        guardrails={
            "output_sanitizer": {
                "enabled": True,
                "strip_patterns": [r"SECRET_TOKEN_\d+"],
            }
        },
    )
    merged = _loader(clients_root).load("tenant_a")
    effective = apply_regulated_overrides(merged)
    cleaned, labels = sanitize_output(
        "Answer with SECRET_TOKEN_123 inside.",
        effective.guardrails,
        effective.compiled,
    )
    assert "SECRET_TOKEN_123" not in cleaned
    assert labels


def test_no_context_skips_llm_and_returns_dont_know_escalation(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root)
    llm = _MockLLM("should not run")

    class _NoContextRetriever:
        def retrieve_with_outcome(self, query, limit=5, mode="hybrid_local", **kwargs):
            return RetrievalOutcome(
                chunks=[],
                no_context=True,
                no_context_message="No relevant sources.",
            )

    orchestrator = ChatOrchestrator(
        llm_provider=llm,
        retriever=_NoContextRetriever(),
        prompt_policy=_MockPolicy(),
        default_model="test",
        config_loader=_loader(clients_root),
    )
    res = orchestrator.answer(ChatRequest(client_id="tenant_a", message="hello", top_k=3))
    assert res.answer == "No relevant sources."
    assert llm.called is False
    assert res.escalation is not None
    assert res.escalation.type == "dont_know"


def test_requires_human_and_escalation_fields_on_crisis(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, crisis_rules=_sample_crisis_rules())
    orchestrator = ChatOrchestrator(
        llm_provider=_MockLLM("unused"),
        retriever=_TrackingRetriever(RetrievalOutcome(chunks=[], no_context=True)),
        prompt_policy=_MockPolicy(),
        default_model="test",
        config_loader=_loader(clients_root),
    )
    res = orchestrator.answer(
        ChatRequest(client_id="tenant_a", message=CRISIS_TRIGGER, top_k=3)
    )
    assert res.requires_human is True
    assert res.escalation is not None
    assert res.escalation.type == "crisis"
    assert res.escalation.message


def test_invalid_crisis_regex_rejected_at_load(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(
        clients_root,
        crisis_rules={
            "enabled": True,
            "categories": [
                {
                    "id": "bad",
                    "match": {"any_patterns": ["(unclosed"]},
                    "response": {"message": "x"},
                }
            ],
        },
    )
    with pytest.raises(ConfigValidationError, match="invalid regex"):
        _loader(clients_root).load("tenant_a")


def test_regulated_orchestrator_end_to_end_with_disclaimer_and_citation(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(
        clients_root,
        regulated=True,
        source_whitelist={
            "allowed_public_domains": ["client.com"],
            "citation_enforcement": {"include_only_cited_sources": True},
        },
        disclaimers={
            "enabled": True,
            "items": [
                {
                    "id": "reg_footer",
                    "enabled": True,
                    "placement": "footer",
                    "when": {"regulated_mode_only": True, "any_answer": True},
                    "text": "Not professional advice.",
                }
            ],
        },
    )
    llm = _MockLLM("Support hours are nine to five [1].")

    class _Retriever:
        def retrieve_with_outcome(self, query, limit=5, mode="hybrid_local", **kwargs):
            return RetrievalOutcome(
                chunks=[
                    _chunk(
                        citation_url="https://client.com/hours",
                        source_visibility="public",
                    )
                ],
                no_context=False,
            )

    orchestrator = ChatOrchestrator(
        llm_provider=llm,
        retriever=_Retriever(),
        prompt_policy=_MockPolicy(),
        default_model="test",
        config_loader=_loader(clients_root),
    )
    res = orchestrator.answer(ChatRequest(client_id="tenant_a", message="hours?", top_k=3))
    assert "[1]" in res.answer
    assert "Not professional advice." in res.answer
    assert len(res.sources) == 1
    assert res.sources[0].url == "https://client.com/hours"
