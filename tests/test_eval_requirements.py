import pytest

from packages.core.eval.models import EvalSuiteConfig
from packages.core.eval.requirements import has_public_citation_config, resolve_eval_requirements
from packages.core.config.models import MergedTenantConfig


def _suite(**overrides) -> EvalSuiteConfig:
    base = {
        "version": 1,
        "client_id": "demo",
        "index_scope": "pending",
        "default_mode": "hybrid_local",
        "thresholds": {},
        "required_categories": [
            "retrieval",
            "answer",
            "safety_off_topic",
            "safety_jailbreak",
            "citation_source",
        ],
        "require_citation_tests": False,
        "placeholder": False,
        "export_formats": ["csv"],
        "bundle_visibility": "public_only",
        "freshness_hours": 24,
    }
    base.update(overrides)
    return EvalSuiteConfig(**base)


def _merged(**whitelist) -> MergedTenantConfig:
    return MergedTenantConfig(
        client_id="demo",
        domain_pack="generic",
        source_whitelist=whitelist,
    )


def test_internal_only_client_drops_citation_requirement() -> None:
    reqs = resolve_eval_requirements(
        suite=_suite(),
        regulated_mode=False,
        merged=_merged(allowed_public_domains=[]),
    )
    assert "citation_source" not in reqs.required_categories
    assert reqs.citation_tests_required is False


def test_public_domains_keep_citation_requirement() -> None:
    reqs = resolve_eval_requirements(
        suite=_suite(),
        regulated_mode=False,
        merged=_merged(allowed_public_domains=["example.com"]),
    )
    assert "citation_source" in reqs.required_categories
    assert reqs.citation_tests_required is True


def test_regulated_client_requires_citation_when_configured() -> None:
    reqs = resolve_eval_requirements(
        suite=_suite(require_citation_tests=True),
        regulated_mode=True,
        merged=_merged(allowed_public_domains=[]),
    )
    assert reqs.citation_tests_required is True


def test_has_public_citation_config() -> None:
    assert has_public_citation_config(_merged(allowed_public_domains=["example.com"])) is True
    assert has_public_citation_config(_merged(allowed_public_domains=[])) is False
