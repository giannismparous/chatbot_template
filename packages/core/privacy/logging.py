from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

FORBIDDEN_LOG_KEYS = frozenset(
    {
        "original_message",
        "history",
        "answer",
        "system_prompt",
        "messages",
        "chunks",
        "text",
        "content",
        "block_reason",
        "api_key",
        "widget_key",
        "admin_token",
    }
)


def privacy_safe_log(event: str, payload: dict[str, Any]) -> None:
    """Emit structured log lines that respect privacy-gated payloads."""
    safe = _strip_forbidden(payload)
    logger.info("%s %s", event, safe)


def _strip_forbidden(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key in FORBIDDEN_LOG_KEYS:
            continue
        if isinstance(value, dict):
            nested = _strip_forbidden(value)
            if nested:
                cleaned[key] = nested
            continue
        if isinstance(value, list):
            continue
        cleaned[key] = value
    return cleaned
