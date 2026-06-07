from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMOutcome:
    text: str
    model_used: str
    provider: str = "gemini"
    blocked: bool = False
    block_reason: str | None = None
    fallback_used: bool = False
    dev_placeholder: bool = False
    truncated: bool = False
    attempts: list[dict[str, Any]] = field(default_factory=list)
