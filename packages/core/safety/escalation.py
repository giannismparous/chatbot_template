from __future__ import annotations

from typing import Any

from packages.core.domain.models import Escalation


def escalation_messages(escalation_rules: dict[str, Any]) -> dict[str, str]:
    messages = escalation_rules.get("messages") or {}
    return {
        "dont_know": str(
            messages.get("dont_know") or "I could not find that in the approved sources."
        ).strip(),
        "low_confidence": str(
            messages.get("low_confidence") or "This answer may be incomplete."
        ).strip(),
        "human_handoff": str(
            messages.get("human_handoff") or "I'll connect you with our team."
        ).strip(),
    }


def build_dont_know_escalation(escalation_rules: dict[str, Any]) -> Escalation:
    message = escalation_messages(escalation_rules)["dont_know"]
    return Escalation(type="dont_know", message=message)


def check_human_handoff(message: str, escalation_rules: dict[str, Any]) -> Escalation | None:
    if not escalation_rules.get("enabled", True):
        return None
    normalized = (message or "").lower()
    for rule in escalation_rules.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        when = rule.get("when") or {}
        keywords = [str(k).lower() for k in (when.get("any_keywords") or []) if k]
        if keywords and any(kw in normalized for kw in keywords):
            rule_type = str(rule.get("type") or "human_handoff")
            messages = escalation_messages(escalation_rules)
            msg = messages.get(rule_type) or messages["human_handoff"]
            return Escalation(type=rule_type, message=msg)
    return None
