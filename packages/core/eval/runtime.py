from __future__ import annotations

import os
from pathlib import Path

from packages.adapters.config.tenant_prompt_policy import TenantPromptPolicyEngine
from packages.adapters.llm.gemini_adapter import GeminiLLMBackend
from packages.adapters.llm.resilient_provider import ResilientLLMProvider
from packages.adapters.retrieval.tenant_retriever_v2 import TenantRetrieverV2
from packages.core.config.loader import TenantConfigLoader
from packages.core.domain.interfaces import LLMProvider
from packages.core.llm.key_pool import LLMKeyPool
from packages.core.llm.models import LLMOutcome
from packages.core.llm.orchestrator import LLMOrchestrator
from packages.core.orchestrator.chat_orchestrator import ChatOrchestrator
from packages.core.stack.factory import project_root
from packages.core.traces.noop_stores import NOOP_METRICS_STORE, NOOP_TRACE_STORE


class ReplayLLMProvider:
    """CI/local replay — not used for default deploy eval."""

    def __init__(self, *, default_text: str = "Eval replay answer with [1].") -> None:
        self._default_text = default_text
        self._responses: dict[str, str] = {}

    def set_response(self, message: str, text: str) -> None:
        self._responses[message.strip().lower()] = text

    def generate_with_outcome(self, system_prompt, messages, *, llm_config=None) -> LLMOutcome:
        user = ""
        for msg in reversed(messages or []):
            if msg.get("role") == "user":
                user = str(msg.get("content") or "")
                break
        text = self._responses.get(user.strip().lower(), self._default_text)
        return LLMOutcome(text=text, model_used="eval-replay", provider="replay")

    def generate(self, system_prompt, messages, model, temperature=0.2) -> str:
        return self.generate_with_outcome(system_prompt, messages).text


def build_eval_orchestrator(
    *,
    clients_root: Path,
    config_loader: TenantConfigLoader,
    llm_mode: str = "live",
    replay_llm: LLMProvider | None = None,
    legacy_knowledge_path: Path | None = None,
) -> ChatOrchestrator:
    root = project_root()
    legacy = legacy_knowledge_path or (
        root / "packages" / "config" / "defaults" / "knowledge.json"
    )
    retriever = TenantRetrieverV2.build_default(
        clients_root=clients_root,
        config_loader=config_loader,
        legacy_fallback_path=str(legacy),
    )
    policy = TenantPromptPolicyEngine(config_loader)

    if llm_mode == "replay":
        llm = replay_llm or ReplayLLMProvider()
    else:
        default_client = os.getenv("DEFAULT_CLIENT_ID", "default")
        merged = config_loader.load(default_client)
        merged_llm = merged.llm or {}
        key_cfg = merged_llm.get("key_pool") or {}
        key_pool = LLMKeyPool.from_env(
            cooldown_seconds=float(key_cfg.get("cooldown_seconds", 60)),
            env_list_var=str(key_cfg.get("env_list_var") or "GEMINI_API_KEYS"),
            env_primary_var=str(key_cfg.get("env_primary_var") or "GEMINI_API_KEY"),
        )
        llm = ResilientLLMProvider(
            LLMOrchestrator(
                backend=GeminiLLMBackend(),
                key_pool=key_pool,
                stack_profile="local",
            )
        )

    return ChatOrchestrator(
        llm_provider=llm,
        retriever=retriever,
        prompt_policy=policy,
        config_loader=config_loader,
        default_model=os.getenv("DEFAULT_MODEL", "gemini-2.5-flash-lite"),
        stack_profile=os.getenv("STACK_PROFILE", "local"),
        trace_store=NOOP_TRACE_STORE,
        metrics_store=NOOP_METRICS_STORE,
    )
