from __future__ import annotations

from typing import Any, Dict, Sequence

from packages.core.domain.interfaces import LLMProvider
from packages.core.llm.models import LLMOutcome
from packages.core.llm.orchestrator import LLMOrchestrator


class ResilientLLMProvider(LLMProvider):
    """LLMProvider facade over LLMOrchestrator (model chain, keys, fallback)."""

    def __init__(self, orchestrator: LLMOrchestrator) -> None:
        self._orchestrator = orchestrator
        self._llm_config: dict[str, Any] = {}

    def set_llm_config(self, llm_config: dict[str, Any]) -> None:
        self._llm_config = llm_config or {}

    def generate_with_outcome(
        self,
        system_prompt: str,
        messages: Sequence[Dict[str, str]],
        *,
        llm_config: dict[str, Any] | None = None,
    ) -> LLMOutcome:
        return self._orchestrator.generate(
            system_prompt=system_prompt,
            messages=messages,
            llm_config=llm_config if llm_config is not None else self._llm_config,
        )

    def generate(
        self,
        system_prompt: str,
        messages: Sequence[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
    ) -> str:
        cfg = dict(self._llm_config)
        defaults = dict(cfg.get("defaults") or {})
        defaults.setdefault("temperature", temperature)
        cfg["defaults"] = defaults
        if model and not cfg.get("model_chain"):
            cfg["model_chain"] = [{"id": "legacy", "model": model, "enabled": True}]
        return self.generate_with_outcome(system_prompt, messages, llm_config=cfg).text
