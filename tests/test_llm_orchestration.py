from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from packages.adapters.llm.gemini_adapter import GeminiLLMBackend, classify_gemini_error
from packages.adapters.llm.resilient_provider import ResilientLLMProvider
from packages.config.loaders import save_yaml
from packages.core.config.loader import TenantConfigLoader
from packages.core.config.models import ConfigValidationError
from packages.core.domain.models import ChatRequest, RetrievedChunk
from packages.core.llm.errors import LLMQuotaError, LLMRateLimitError, LLMTimeoutError
from packages.core.llm.key_pool import LLMKeyPool
from packages.core.llm.orchestrator import LLMOrchestrator
from packages.core.orchestrator.chat_orchestrator import ChatOrchestrator
from packages.core.ports.llm_backend import LLMGenerateResult
from packages.core.retrieval.models import RetrievalOutcome

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"

FALLBACK_MSG = "Configured safe fallback message."
PRIMARY_MODEL = "gemini-primary-test"
FALLBACK_MODEL = "gemini-fallback-test"


def _base_llm_config(**overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "provider": "gemini",
        "defaults": {"temperature": 0.2, "timeout_seconds": 5},
        "model_chain": [
            {"id": "primary", "model": PRIMARY_MODEL, "enabled": True},
            {"id": "strong", "model": FALLBACK_MODEL, "enabled": True, "fallback_only": True},
        ],
        "retry": {
            "max_retries_per_model": 2,
            "backoff_base_ms": 1,
            "backoff_max_ms": 5,
            "retry_on": ["rate_limit", "timeout", "server_error"],
        },
        "blocked_content": {
            "try_next_model": True,
            "fallback_message": FALLBACK_MSG,
            "requires_human": False,
            "escalation_type": "provider_blocked",
        },
        "dev": {"allow_missing_key_placeholder": False},
    }
    cfg.update(overrides)
    return cfg


def _orchestrator(
    generate_fn,
    *,
    keys: list[str] | None = None,
    llm_config: dict | None = None,
    stack_profile: str = "local",
    cooldown_seconds: float = 60.0,
) -> LLMOrchestrator:
    key_list = ["key-one"] if keys is None else keys
    pool = LLMKeyPool(keys=key_list, cooldown_seconds=cooldown_seconds)
    return LLMOrchestrator(
        backend=GeminiLLMBackend(generate_fn=generate_fn),
        key_pool=pool,
        stack_profile=stack_profile,
        default_model_env="env-default-model",
    )


def test_primary_model_success_uses_only_primary() -> None:
    calls: list[str] = []

    def _generate(**kwargs):
        calls.append(kwargs["model"])
        return LLMGenerateResult(text="Primary answer.")

    outcome = _orchestrator(_generate, keys=["k1"]).generate(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        llm_config=_base_llm_config(),
    )
    assert outcome.text == "Primary answer."
    assert outcome.model_used == PRIMARY_MODEL
    assert calls == [PRIMARY_MODEL]


def test_primary_blocked_tries_fallback_model() -> None:
    calls: list[str] = []

    def _generate(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == PRIMARY_MODEL:
            return LLMGenerateResult(text="", blocked=True, block_reason="PROHIBITED_CONTENT")
        return LLMGenerateResult(text="Fallback answer.")

    outcome = _orchestrator(_generate, keys=["k1"]).generate(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        llm_config=_base_llm_config(),
    )
    assert outcome.text == "Fallback answer."
    assert outcome.model_used == FALLBACK_MODEL
    assert calls == [PRIMARY_MODEL, FALLBACK_MODEL]


def test_fallback_only_model_skipped_when_primary_succeeds() -> None:
    calls: list[str] = []

    def _generate(**kwargs):
        calls.append(kwargs["model"])
        return LLMGenerateResult(text="Primary only.")

    _orchestrator(_generate, keys=["k1"]).generate(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        llm_config=_base_llm_config(),
    )
    assert calls == [PRIMARY_MODEL]


def test_quota_on_key1_rotates_to_key2() -> None:
    calls: list[str] = []

    def _generate(**kwargs):
        calls.append(kwargs["api_key"])
        if kwargs["api_key"] == "key-one":
            raise LLMQuotaError("quota exceeded")
        return LLMGenerateResult(text="From key two.")

    outcome = _orchestrator(_generate, keys=["key-one", "key-two"]).generate(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        llm_config=_base_llm_config(),
    )
    assert outcome.text == "From key two."
    assert "key-one" in calls
    assert "key-two" in calls


def test_all_keys_in_cooldown_returns_fallback_without_hanging() -> None:
    pool = LLMKeyPool(keys=["key-one", "key-two"], cooldown_seconds=3600)
    pool.mark_cooldown("key-one")
    pool.mark_cooldown("key-two")

    def _generate(**kwargs):
        return LLMGenerateResult(text="Should not run.")

    start = time.time()
    outcome = LLMOrchestrator(
        backend=GeminiLLMBackend(generate_fn=_generate),
        key_pool=pool,
        stack_profile="local",
        default_model_env="env-default",
    ).generate(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        llm_config=_base_llm_config(),
    )
    elapsed = time.time() - start
    assert elapsed < 2.0
    assert outcome.fallback_used is True
    assert outcome.text == FALLBACK_MSG


def test_429_retry_succeeds_after_backoff() -> None:
    attempts = {"count": 0}

    def _generate(**kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise LLMRateLimitError("429 rate limit")
        return LLMGenerateResult(text="Retried OK.")

    outcome = _orchestrator(_generate, keys=["k1"]).generate(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        llm_config=_base_llm_config(),
    )
    assert outcome.text == "Retried OK."
    assert attempts["count"] == 2


def test_timeout_retry_behavior() -> None:
    attempts = {"count": 0}

    def _generate(**kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise LLMTimeoutError("timed out")
        return LLMGenerateResult(text="After timeout retry.")

    outcome = _orchestrator(_generate, keys=["k1"]).generate(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        llm_config=_base_llm_config(),
    )
    assert outcome.text == "After timeout retry."
    assert attempts["count"] == 2


def test_prohibited_content_returns_safe_fallback_without_raw_provider_text() -> None:
    raw_error = "PROHIBITED_CONTENT: dangerous policy violation at projects/xyz"

    def _generate(**kwargs):
        raise classify_gemini_error(Exception(raw_error))

    outcome = _orchestrator(_generate, keys=["k1"]).generate(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        llm_config=_base_llm_config(
            blocked_content={
                "try_next_model": False,
                "fallback_message": FALLBACK_MSG,
            }
        ),
    )
    assert outcome.fallback_used is True
    assert outcome.text == FALLBACK_MSG
    assert "PROHIBITED_CONTENT" not in outcome.text
    assert "projects/xyz" not in outcome.text


def test_all_models_blocked_returns_configured_fallback_message() -> None:
    def _generate(**kwargs):
        return LLMGenerateResult(text="", blocked=True, block_reason="SAFETY")

    outcome = _orchestrator(_generate, keys=["k1"]).generate(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        llm_config=_base_llm_config(),
    )
    assert outcome.fallback_used is True
    assert outcome.text == FALLBACK_MSG


def test_missing_key_with_placeholder_enabled_returns_dev_placeholder() -> None:
    outcome = _orchestrator(lambda **k: LLMGenerateResult(text="x"), keys=[]).generate(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello there"}],
        llm_config=_base_llm_config(dev={"allow_missing_key_placeholder": True}),
    )
    assert outcome.dev_placeholder is True
    assert "Gemini key missing" in outcome.text
    assert "hello there" in outcome.text


def test_missing_key_with_placeholder_disabled_returns_fallback() -> None:
    outcome = _orchestrator(lambda **k: LLMGenerateResult(text="x"), keys=[]).generate(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        llm_config=_base_llm_config(dev={"allow_missing_key_placeholder": False}),
    )
    assert outcome.fallback_used is True
    assert outcome.text == FALLBACK_MSG


def test_missing_key_placeholder_not_allowed_on_firebase_profile() -> None:
    outcome = _orchestrator(
        lambda **k: LLMGenerateResult(text="x"),
        keys=[],
        stack_profile="firebase",
    ).generate(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        llm_config=_base_llm_config(dev={"allow_missing_key_placeholder": True}),
    )
    assert outcome.fallback_used is True
    assert outcome.dev_placeholder is False


def test_llm_yaml_client_override_works(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    config_dir = clients_root / "tenant_a" / "config"
    config_dir.mkdir(parents=True)
    save_yaml(
        str(config_dir / "client.yaml"),
        {"client_id": "tenant_a", "display_name": "Tenant A", "domain_pack": "generic"},
    )
    save_yaml(
        str(config_dir / "llm.yaml"),
        {"defaults": {"temperature": 0.9}},
    )
    merged = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS).load("tenant_a")
    assert float((merged.llm.get("defaults") or {})["temperature"]) == 0.9


def test_invalid_llm_yaml_fails_validation(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    config_dir = clients_root / "tenant_a" / "config"
    config_dir.mkdir(parents=True)
    save_yaml(
        str(config_dir / "client.yaml"),
        {"client_id": "tenant_a", "display_name": "Tenant A", "domain_pack": "generic"},
    )
    save_yaml(
        str(config_dir / "llm.yaml"),
        {"defaults": {"timeout_seconds": 999}, "retry": {"retry_on": ["not_a_real_kind"]}},
    )
    with pytest.raises(ConfigValidationError):
        TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS).load("tenant_a")


def _write_client(clients_root: Path, *, regulated: bool = False, disclaimers: dict | None = None) -> None:
    config_dir = clients_root / "tenant_a" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    client = {"client_id": "tenant_a", "display_name": "Tenant A", "domain_pack": "generic"}
    if regulated:
        client["regulated_mode"] = True
    save_yaml(str(config_dir / "client.yaml"), client)
    if disclaimers:
        save_yaml(str(config_dir / "disclaimers.yaml"), disclaimers)


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        id="c1",
        text="Doc\nbody",
        source="uploads/a.txt",
        score=0.9,
        metadata={"title": "Doc", "internal_url": "uploads/a.txt", "source_visibility": "internal"},
    )


def test_fallback_used_skips_citation_enforcement_and_empty_sources(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root)
    save_yaml(
        str(clients_root / "tenant_a" / "config" / "llm.yaml"),
        _base_llm_config(),
    )

    def _generate(**kwargs):
        return LLMGenerateResult(text="", blocked=True, block_reason="SAFETY")

    llm_orch = _orchestrator(_generate, keys=["k1"])
    provider = ResilientLLMProvider(llm_orch)

    class _Retriever:
        def retrieve_with_outcome(self, query, limit=5, mode="hybrid_local", **kwargs):
            return RetrievalOutcome(chunks=[_chunk()], no_context=False)

    orchestrator = ChatOrchestrator(
        llm_provider=provider,
        retriever=_Retriever(),
        prompt_policy=_MockPolicy(),
        config_loader=TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS),
    )
    res = orchestrator.answer(ChatRequest(client_id="tenant_a", message="hello", top_k=3))
    assert res.sources == []
    assert res.confidence == 0.0
    assert res.trace.get("llm_skipped_citation_pipeline") is True
    assert res.answer == FALLBACK_MSG
    assert "[1]" not in res.answer


def test_regulated_fallback_still_gets_disclaimer_and_sanitizer(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(
        clients_root,
        regulated=True,
        disclaimers={
            "enabled": True,
            "items": [
                {
                    "id": "reg_footer",
                    "enabled": True,
                    "placement": "footer",
                    "when": {"regulated_mode_only": True, "any_answer": True},
                    "text": "Regulated disclaimer footer.",
                }
            ],
        },
    )
    save_yaml(
        str(clients_root / "tenant_a" / "config" / "guardrails.yaml"),
        {
            "output_sanitizer": {
                "enabled": True,
                "strip_patterns": [r"SECRET_TOKEN_\d+"],
            }
        },
    )

    save_yaml(
        str(clients_root / "tenant_a" / "config" / "llm.yaml"),
        _base_llm_config(),
    )

    def _blocked(**kwargs):
        return LLMGenerateResult(text="Answer SECRET_TOKEN_99.", blocked=True, block_reason="SAFETY")

    orchestrator = ChatOrchestrator(
        llm_provider=ResilientLLMProvider(_orchestrator(_blocked, keys=["k1"])),
        retriever=_BlockedRetriever(),
        prompt_policy=_MockPolicy(),
        config_loader=TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS),
    )
    res = orchestrator.answer(ChatRequest(client_id="tenant_a", message="hello", top_k=3))
    assert "Regulated disclaimer footer." in res.answer
    assert "SECRET_TOKEN_99" not in res.answer


def test_blocked_fallback_sets_provider_blocked_escalation(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root)
    save_yaml(
        str(clients_root / "tenant_a" / "config" / "llm.yaml"),
        _base_llm_config(),
    )

    def _generate(**kwargs):
        return LLMGenerateResult(text="", blocked=True, block_reason="SAFETY")

    orchestrator = ChatOrchestrator(
        llm_provider=ResilientLLMProvider(_orchestrator(_generate, keys=["k1"])),
        retriever=_BlockedRetriever(),
        prompt_policy=_MockPolicy(),
        config_loader=TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS),
    )
    res = orchestrator.answer(ChatRequest(client_id="tenant_a", message="hello", top_k=3))
    assert res.escalation is not None
    assert res.escalation.type == "provider_blocked"
    assert res.requires_human is False


class _MockPolicy:
    def build_system_prompt(self, client_id: str, mode: str) -> str:
        return "system"


class _BlockedRetriever:
    def retrieve_with_outcome(self, query, limit=5, mode="hybrid_local", **kwargs):
        return RetrievalOutcome(chunks=[_chunk()], no_context=False)
