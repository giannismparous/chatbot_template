from __future__ import annotations

from typing import Any


def _pick_locale_text(item: dict[str, Any], locale: dict[str, Any]) -> str:
    lang = str(locale.get("primary_language") or "en").strip().lower()
    for key in (f"text_{lang}", "text", "text_en"):
        value = item.get(key)
        if value and str(value).strip():
            return str(value).strip()
    return ""


def inject_disclaimers(
    answer: str,
    disclaimers: dict[str, Any],
    *,
    regulated_mode: bool,
    locale: dict[str, Any],
    crisis_path: bool = False,
) -> tuple[str, list[str]]:
    if crisis_path or not disclaimers.get("enabled", True):
        return answer, []

    applied: list[str] = []
    result = answer.strip()
    normalized_answer = " ".join(result.lower().split())

    for item in disclaimers.get("items") or []:
        if not isinstance(item, dict) or not item.get("enabled", True):
            continue
        item_id = str(item.get("id") or "")
        when = item.get("when") or {}
        if when.get("regulated_mode_only") and not regulated_mode:
            continue
        if when.get("any_answer") is False:
            continue

        text = _pick_locale_text(item, locale)
        if not text:
            continue

        if item.get("dedupe", True):
            norm_text = " ".join(text.lower().split())
            if norm_text and norm_text in normalized_answer:
                continue

        placement = str(item.get("placement") or "footer").lower()
        if placement in ("header", "both"):
            result = f"{text}\n\n{result}".strip()
        if placement in ("footer", "both"):
            result = f"{result}\n\n{text}".strip()
        if item_id:
            applied.append(item_id)

    return result.strip(), applied
