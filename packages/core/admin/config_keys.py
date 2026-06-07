from __future__ import annotations

from packages.core.config.loader import CONFIG_FILES, FAQ_FILENAME

# Allowlisted admin config keys → tenant override filenames.
CONFIG_KEY_FILES: dict[str, str] = {
    **CONFIG_FILES,
    "faq": FAQ_FILENAME,
    "compliance": "compliance.yaml",
    "source_mapping": "source_mapping.yaml",
    "web_sources": "web_sources.yaml",
}

# Keys restricted to platform_admin (client_admin scaffold only — not enabled Phase 11).
PLATFORM_ONLY_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "privacy",
        "source_whitelist",
        "source_mapping",
        "web_sources",
        "guardrails",
        "crisis_rules",
        "llm",
        "compliance",
        "ingestion",
        "retrieval_rules",
        "disclaimers",
        "escalation_rules",
        "domain_pack",
    }
)


def normalize_config_key(key: str) -> str:
    normalized = (key or "").strip().lower().replace("_", "-")
    return normalized.replace("-", "_")


def resolve_config_key(key: str) -> str:
    """Resolve URL key to canonical config key or raise ValueError."""
    raw = (key or "").strip()
    if not raw:
        raise ValueError("Missing config key.")
    if ".." in raw or "/" in raw or "\\" in raw or "\x00" in raw:
        raise ValueError("Invalid config key.")
    canonical = normalize_config_key(raw)
    if canonical not in CONFIG_KEY_FILES:
        raise ValueError(f"Config key not allowlisted: {key!r}")
    return canonical


def config_filename(key: str) -> str:
    canonical = resolve_config_key(key)
    return CONFIG_KEY_FILES[canonical]
