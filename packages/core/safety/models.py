from __future__ import annotations

from dataclasses import dataclass, field

from packages.core.domain.models import Escalation


@dataclass
class SafetyBlock:
    """Deterministic pre-LLM safety stop (crisis or input guard)."""

    kind: str
    answer: str
    category_id: str | None = None
    requires_human: bool = False
    escalation: Escalation | None = None
    trace: dict = field(default_factory=dict)


@dataclass
class CompiledSafetyPatterns:
    crisis_category_patterns: dict[str, list[re.Pattern[str]]] = field(default_factory=dict)
    crisis_exclusion_patterns: list = field(default_factory=list)
    jailbreak_patterns: list = field(default_factory=list)
    off_topic_exempt_patterns: list = field(default_factory=list)
    output_strip_patterns: list = field(default_factory=list)
    regulated_exempt_patterns: list = field(default_factory=list)
    regulated_factual_patterns: list = field(default_factory=list)


# Late import for type hints only — patterns are re.Pattern at runtime
import re  # noqa: E402
