from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from packages.core.domain.models import ChatMessage


@dataclass
class RewriteResult:
    original_query: str
    rewritten_query: str
    rewrite_reason: str
    is_follow_up: bool


def _follow_up_cfg(locale: dict[str, Any]) -> dict[str, Any]:
    raw = locale.get("follow_up") or {}
    return raw if isinstance(raw, dict) else {}


def _last_substantive_user(history: list[ChatMessage]) -> str | None:
    for msg in reversed(history):
        if msg.role == "user" and len(msg.content.strip()) > 12:
            return msg.content.strip()
    return None


def _last_assistant(history: list[ChatMessage]) -> str | None:
    for msg in reversed(history):
        if msg.role == "assistant" and msg.content.strip():
            return msg.content.strip()
    return None


def rewrite_follow_up_query(
    message: str,
    history: list[ChatMessage],
    locale: dict[str, Any],
    *,
    content_allowed: bool,
) -> RewriteResult:
    original = (message or "").strip()
    if not original or not content_allowed or not history:
        return RewriteResult(original, original, "none", False)

    cfg = _follow_up_cfg(locale)
    if not cfg.get("enabled", True):
        return RewriteResult(original, original, "none", False)

    normalized = original.lower()
    max_short = int(cfg.get("max_short_chars", 12))
    affirmatives = {str(x).lower() for x in (cfg.get("affirmatives") or []) if str(x).strip()}
    continuations = {str(x).lower() for x in (cfg.get("continuations") or []) if str(x).strip()}
    deictics = {str(x).lower() for x in (cfg.get("deictics") or []) if str(x).strip()}

    last_user = _last_substantive_user(history)
    last_assistant = _last_assistant(history)

    if normalized in affirmatives and last_assistant:
        topic = last_user or last_assistant[:80]
        return RewriteResult(original, topic, "affirmative_to_last_question", True)

    if normalized in continuations and last_user:
        return RewriteResult(original, f"{last_user} additional details", "continuation", True)

    if len(original) <= max_short and last_user:
        return RewriteResult(original, f"{last_user} {original}", "short_reply_expansion", True)

    tokens = normalized.split()
    if tokens and all(t in deictics for t in tokens) and last_user:
        return RewriteResult(original, f"{last_user} {original}", "topic_blend", True)

    return RewriteResult(original, original, "none", False)
