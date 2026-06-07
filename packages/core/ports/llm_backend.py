from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Sequence


@dataclass
class LLMGenerateResult:
    text: str
    blocked: bool = False
    block_reason: str | None = None
    truncated: bool = False


class LLMBackend(ABC):
    """Provider-specific single-attempt LLM transport (Gemini in Phase 7)."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate_once(
        self,
        *,
        api_key: str,
        model: str,
        system_prompt: str,
        messages: Sequence[Dict[str, str]],
        temperature: float,
        timeout_seconds: float,
        max_output_tokens: int | None = None,
    ) -> LLMGenerateResult:
        raise NotImplementedError
