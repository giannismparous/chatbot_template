from __future__ import annotations

from typing import Any

from packages.core.domain.models import Escalation
from packages.core.safety.config import EffectiveSafetyConfig, _normalize_text
from packages.core.safety.models import SafetyBlock


def _pick_locale_message(data: dict[str, Any], locale: dict[str, Any], key: str = "message") -> str:
    lang = str(locale.get("primary_language") or "en").strip().lower()
    for candidate in (f"{key}_{lang}", key, f"{key}_en"):
        value = data.get(candidate)
        if value and str(value).strip():
            return str(value).strip()
    return ""


def _format_hotlines(hotlines: list[Any], fmt: str) -> str:
    lines: list[str] = []
    for item in hotlines:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("label_en") or "Hotline").strip()
        number = str(item.get("number") or "").strip()
        if not number:
            continue
        try:
            lines.append(fmt.format(label=label, number=number, url=item.get("url") or ""))
        except (KeyError, ValueError):
            lines.append(f"{label}: {number}")
    return "\n".join(lines)


def _keyword_hits(text: str, keywords: list[Any], *, min_hits: int) -> bool:
    if not keywords:
        return False
    hits = sum(1 for kw in keywords if kw and str(kw).lower() in text)
    return hits >= max(1, min_hits)


def _pattern_hits(text: str, patterns: list) -> bool:
    return any(p.search(text) for p in patterns)


def check_crisis(message: str, effective: EffectiveSafetyConfig) -> SafetyBlock | None:
    crisis_rules = effective.crisis_rules
    if not crisis_rules.get("enabled", True) and not effective.regulated_mode:
        return None

    norm_cfg = crisis_rules.get("normalization") or {}
    normalized = _normalize_text(message, lowercase=bool(norm_cfg.get("lowercase", True)))

    exclusions = crisis_rules.get("exclusions") or {}
    if _keyword_hits(normalized, exclusions.get("any_keywords") or [], min_hits=1):
        return None
    if _pattern_hits(normalized, effective.compiled.crisis_exclusion_patterns):
        return None

    categories = sorted(
        [c for c in (crisis_rules.get("categories") or []) if isinstance(c, dict)],
        key=lambda c: int(c.get("priority") or 0),
        reverse=True,
    )

    for category in categories:
        if not category.get("enabled", True):
            continue
        cat_id = str(category.get("id") or "")
        match = category.get("match") or {}
        min_hits = int(match.get("min_keyword_hits") or 1)
        keyword_hit = _keyword_hits(normalized, match.get("any_keywords") or [], min_hits=min_hits)
        pattern_hit = _pattern_hits(
            normalized,
            effective.compiled.crisis_category_patterns.get(cat_id, []),
        )
        if not keyword_hit and not pattern_hit:
            continue

        response = category.get("response") or {}
        answer = _pick_locale_message(response, effective.locale)
        if not answer:
            fallback = crisis_rules.get("fallback") or {}
            answer = str(fallback.get("message") or "").strip()
        hotline_fmt = str(crisis_rules.get("hotline_format") or "{label}: {number}")
        hotline_text = _format_hotlines(category.get("hotlines") or [], hotline_fmt)
        if hotline_text:
            answer = f"{answer}\n{hotline_text}".strip()

        flags = category.get("flags") or {}
        requires_human = bool(flags.get("requires_human", True))
        escalation = Escalation(
            type="crisis",
            message=answer,
            contact_hint=hotline_text.split("\n")[0] if hotline_text else None,
        )
        return SafetyBlock(
            kind="crisis",
            category_id=cat_id,
            answer=answer,
            requires_human=requires_human,
            escalation=escalation,
            trace={"crisis_hit": True, "crisis_category": cat_id},
        )

    return None
