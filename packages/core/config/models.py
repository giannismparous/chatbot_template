from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ConfigValidationError(ValueError):
    pass


@dataclass
class MergedTenantConfig:
    client_id: str
    domain_pack: str
    client: dict[str, Any] = field(default_factory=dict)
    prompt_policy: dict[str, Any] = field(default_factory=dict)
    themes: dict[str, Any] = field(default_factory=dict)
    locale: dict[str, Any] = field(default_factory=dict)
    privacy: dict[str, Any] = field(default_factory=dict)
    source_whitelist: dict[str, Any] = field(default_factory=dict)
    ingestion: dict[str, Any] = field(default_factory=dict)
    retrieval_rules: dict[str, Any] = field(default_factory=dict)
    faq: dict[str, Any] = field(default_factory=dict)
    guardrails: dict[str, Any] = field(default_factory=dict)
    crisis_rules: dict[str, Any] = field(default_factory=dict)
    disclaimers: dict[str, Any] = field(default_factory=dict)
    escalation_rules: dict[str, Any] = field(default_factory=dict)
    llm: dict[str, Any] = field(default_factory=dict)


REQUIRED_CLIENT_KEYS = ("display_name",)
REQUIRED_PROMPT_KEYS = ("base_system_prompt",)
REQUIRED_THEME_KEYS = ("colors",)


def validate_merged_config(merged: MergedTenantConfig) -> None:
    missing: list[str] = []

    for key in REQUIRED_CLIENT_KEYS:
        if not merged.client.get(key):
            missing.append(f"client.{key}")

    for key in REQUIRED_PROMPT_KEYS:
        if not merged.prompt_policy.get(key):
            missing.append(f"prompt_policy.{key}")

    for key in REQUIRED_THEME_KEYS:
        if key not in merged.themes:
            missing.append(f"themes.{key}")

    if missing:
        raise ConfigValidationError(
            f"Client {merged.client_id!r} missing required config after merge: {', '.join(missing)}"
        )
