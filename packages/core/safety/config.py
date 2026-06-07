from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from packages.core.config.models import ConfigValidationError, MergedTenantConfig
from packages.core.domain.models import Escalation
from packages.core.safety.regex_patterns import compile_pattern_list


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
    crisis_exclusion_patterns: list[re.Pattern[str]] = field(default_factory=list)
    jailbreak_patterns: list[re.Pattern[str]] = field(default_factory=list)
    output_strip_patterns: list[re.Pattern[str]] = field(default_factory=list)
    regulated_exempt_patterns: list[re.Pattern[str]] = field(default_factory=list)
    regulated_factual_patterns: list[re.Pattern[str]] = field(default_factory=list)


@dataclass
class EffectiveSafetyConfig:
    regulated_mode: bool
    crisis_rules: dict[str, Any]
    guardrails: dict[str, Any]
    disclaimers: dict[str, Any]
    escalation_rules: dict[str, Any]
    source_whitelist: dict[str, Any]
    locale: dict[str, Any]
    compiled: CompiledSafetyPatterns


def _normalize_text(text: str, *, lowercase: bool = True) -> str:
    value = unicodedata.normalize("NFC", text or "")
    if lowercase:
        value = value.lower()
    return value.strip()


def compile_safety_patterns(
    crisis_rules: dict[str, Any],
    guardrails: dict[str, Any],
) -> CompiledSafetyPatterns:
    compiled = CompiledSafetyPatterns()
    exclusions = crisis_rules.get("exclusions") or {}
    compiled.crisis_exclusion_patterns = compile_pattern_list(
        exclusions.get("any_patterns") or [],
        context="crisis_rules.exclusions.any_patterns",
    )

    for category in crisis_rules.get("categories") or []:
        if not isinstance(category, dict):
            continue
        cat_id = str(category.get("id") or "")
        if not cat_id:
            continue
        match = category.get("match") or {}
        compiled.crisis_category_patterns[cat_id] = compile_pattern_list(
            match.get("any_patterns") or [],
            context=f"crisis_rules.categories.{cat_id}.any_patterns",
        )

    input_guard = guardrails.get("input_guard") or {}
    jailbreak = input_guard.get("jailbreak") or {}
    compiled.jailbreak_patterns = compile_pattern_list(
        jailbreak.get("any_patterns") or [],
        context="guardrails.input_guard.jailbreak.any_patterns",
    )

    output_sanitizer = guardrails.get("output_sanitizer") or {}
    compiled.output_strip_patterns = compile_pattern_list(
        output_sanitizer.get("strip_patterns") or [],
        context="guardrails.output_sanitizer.strip_patterns",
    )

    regulated = guardrails.get("regulated_profile") or {}
    compiled.regulated_exempt_patterns = compile_pattern_list(
        regulated.get("exempt_sentence_patterns") or [],
        context="guardrails.regulated_profile.exempt_sentence_patterns",
    )
    compiled.regulated_factual_patterns = compile_pattern_list(
        regulated.get("factual_claim_patterns") or [],
        context="guardrails.regulated_profile.factual_claim_patterns",
    )
    return compiled


def validate_safety_config(merged: MergedTenantConfig) -> None:
    """Compile all safety regex at load; invalid patterns fail config validation."""
    compile_safety_patterns(merged.crisis_rules or {}, merged.guardrails or {})


def apply_regulated_overrides(merged: MergedTenantConfig) -> EffectiveSafetyConfig:
    regulated_mode = bool(merged.client.get("regulated_mode"))
    source_whitelist = dict(merged.source_whitelist or {})
    guardrails = dict(merged.guardrails or {})
    crisis_rules = dict(merged.crisis_rules or {})

    if regulated_mode:
        crisis_rules["enabled"] = True
        guardrails["enabled"] = True
        source_whitelist["show_public_sources_only"] = True
        rules = dict(source_whitelist.get("citation_url_rules") or {})
        rules["allow_only_whitelisted"] = True
        source_whitelist["citation_url_rules"] = rules
        enforcement = dict(source_whitelist.get("citation_enforcement") or {})
        enforcement["require_citation_markers"] = True
        source_whitelist["citation_enforcement"] = enforcement
        profile = dict(guardrails.get("regulated_profile") or {})
        profile["require_claim_level_citations"] = True
        guardrails["regulated_profile"] = profile

    compiled = compile_safety_patterns(crisis_rules, guardrails)
    return EffectiveSafetyConfig(
        regulated_mode=regulated_mode,
        crisis_rules=crisis_rules,
        guardrails=guardrails,
        disclaimers=dict(merged.disclaimers or {}),
        escalation_rules=dict(merged.escalation_rules or {}),
        source_whitelist=source_whitelist,
        locale=dict(merged.locale or {}),
        compiled=compiled,
    )
