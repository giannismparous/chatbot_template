from __future__ import annotations

from dataclasses import dataclass

from packages.core.config.models import MergedTenantConfig
from packages.core.eval.models import EvalSuiteConfig


@dataclass(frozen=True)
class EvalRequirements:
    required_categories: list[str]
    citation_tests_required: bool
    placeholder: bool


def has_public_citation_config(merged: MergedTenantConfig) -> bool:
    whitelist = merged.source_whitelist or {}
    domains = whitelist.get("allowed_public_domains") or []
    return any(str(domain).strip() for domain in domains)


def resolve_eval_requirements(
    *,
    suite: EvalSuiteConfig,
    regulated_mode: bool,
    merged: MergedTenantConfig,
) -> EvalRequirements:
    """Derive deploy-relevant categories for internal-only vs public-citation clients."""
    required = list(suite.required_categories)
    has_public = has_public_citation_config(merged)

    if regulated_mode and suite.require_citation_tests:
        citation_tests_required = True
    elif has_public and "citation_source" in required:
        citation_tests_required = True
    else:
        citation_tests_required = False
        required = [cat for cat in required if cat != "citation_source"]

    return EvalRequirements(
        required_categories=required,
        citation_tests_required=citation_tests_required,
        placeholder=bool(suite.placeholder),
    )
