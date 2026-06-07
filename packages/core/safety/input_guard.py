from __future__ import annotations

from typing import Any

from packages.core.domain.models import Escalation
from packages.core.safety.config import EffectiveSafetyConfig, _normalize_text
from packages.core.safety.models import SafetyBlock


def check_input_guard(message: str, effective: EffectiveSafetyConfig) -> SafetyBlock | None:
    guardrails = effective.guardrails
    if not guardrails.get("enabled", True):
        return None

    input_guard = guardrails.get("input_guard") or {}
    if not input_guard.get("enabled", True):
        return None

    normalized = _normalize_text(message)

    jailbreak = input_guard.get("jailbreak") or {}
    for kw in jailbreak.get("any_keywords") or []:
        if kw and str(kw).lower() in normalized:
            return _blocked("jailbreak_keyword", input_guard, effective)
    if any(p.search(normalized) for p in effective.compiled.jailbreak_patterns):
        return _blocked("jailbreak_pattern", input_guard, effective)

    off_topic = input_guard.get("off_topic") or {}
    if off_topic.get("enabled", False):
        allowed = [str(k).lower() for k in (off_topic.get("allowed_topic_keywords") or []) if k]
        if allowed and not any(kw in normalized for kw in allowed):
            block_message = str(off_topic.get("block_message") or "").strip()
            if not block_message:
                block_message = "I can only help with topics related to this service."
            escalation = Escalation(type="input_blocked", message=block_message)
            return SafetyBlock(
                kind="input_guard",
                answer=block_message,
                requires_human=False,
                escalation=escalation,
                trace={"input_blocked": True, "input_block_reason": "off_topic"},
            )

    return None


def _blocked(reason: str, input_guard: dict[str, Any], effective: EffectiveSafetyConfig) -> SafetyBlock:
    jailbreak = input_guard.get("jailbreak") or {}
    block_message = str(jailbreak.get("block_message") or "").strip()
    if not block_message:
        block_message = "I cannot process that request."
    escalation = Escalation(type="input_blocked", message=block_message)
    return SafetyBlock(
        kind="input_guard",
        answer=block_message,
        requires_human=False,
        escalation=escalation,
        trace={"input_blocked": True, "input_block_reason": reason},
    )
