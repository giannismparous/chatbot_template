from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EvalCategory = Literal[
    "retrieval",
    "answer",
    "safety_off_topic",
    "safety_jailbreak",
    "safety_crisis",
    "citation_source",
]

CASE_CATEGORIES = frozenset(
    {
        "retrieval",
        "answer",
        "safety_off_topic",
        "safety_jailbreak",
        "safety_crisis",
        "citation_source",
    }
)

DEFAULT_REQUIRED = [
    "retrieval",
    "answer",
    "safety_off_topic",
    "safety_jailbreak",
]


@dataclass
class EvalExpectations:
    expected_contains: list[str] = field(default_factory=list)
    expected_not_contains: list[str] = field(default_factory=list)
    expected_chunk_ids: list[str] = field(default_factory=list)
    expected_top_k_contains: list[str] = field(default_factory=list)
    expected_no_context: bool | None = None
    expected_escalation: str | None = None
    expected_requires_human: bool | None = None
    expected_sources_domains: list[str] = field(default_factory=list)
    expected_sources_min_count: int | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> EvalExpectations:
        data = raw or {}
        sources = data.get("expected_sources") or {}
        domains = sources.get("domains") if isinstance(sources, dict) else []
        min_count = sources.get("min_count") if isinstance(sources, dict) else None
        esc = data.get("expected_escalation")
        return cls(
            expected_contains=[str(x) for x in (data.get("expected_contains") or [])],
            expected_not_contains=[str(x) for x in (data.get("expected_not_contains") or [])],
            expected_chunk_ids=[str(x) for x in (data.get("expected_chunk_ids") or [])],
            expected_top_k_contains=[str(x) for x in (data.get("expected_top_k_contains") or [])],
            expected_no_context=data.get("expected_no_context"),
            expected_escalation=str(esc) if esc is not None else None,
            expected_requires_human=data.get("expected_requires_human"),
            expected_sources_domains=[str(x).lower() for x in (domains or [])],
            expected_sources_min_count=int(min_count) if min_count is not None else None,
        )


@dataclass
class EvalCase:
    id: str
    category: str
    message: str
    mode: str | None = None
    top_k: int = 5
    history: list[dict[str, str]] = field(default_factory=list)
    expect: EvalExpectations = field(default_factory=EvalExpectations)


@dataclass
class EvalSuiteConfig:
    version: int
    client_id: str
    index_scope: str
    default_mode: str
    thresholds: dict[str, float]
    required_categories: list[str]
    require_citation_tests: bool
    placeholder: bool
    export_formats: list[str]
    bundle_visibility: str
    freshness_hours: float

    @classmethod
    def from_dict(cls, client_id: str, raw: dict[str, Any]) -> EvalSuiteConfig:
        target = raw.get("target") or {}
        thresholds = raw.get("thresholds") or {}
        export = (raw.get("export") or {}).get("reviewer") or {}
        regulated = raw.get("regulated") or {}
        return cls(
            version=int(raw.get("version", 1)),
            client_id=str(raw.get("client_id") or client_id),
            index_scope=str(target.get("index_scope") or "pending"),
            default_mode=str(target.get("mode") or "hybrid_local"),
            thresholds={
                "retrieval_min_pass_rate": float(thresholds.get("retrieval_min_pass_rate", 0.9)),
                "answer_min_pass_rate": float(thresholds.get("answer_min_pass_rate", 0.85)),
                "safety_min_pass_rate": float(thresholds.get("safety_min_pass_rate", 1.0)),
                "citation_min_pass_rate": float(thresholds.get("citation_min_pass_rate", 1.0)),
                "overall_min_pass_rate": float(thresholds.get("overall_min_pass_rate", 1.0)),
            },
            required_categories=list(raw.get("required_categories") or DEFAULT_REQUIRED),
            require_citation_tests=bool(regulated.get("require_citation_tests", False)),
            placeholder=bool(raw.get("placeholder", False)),
            export_formats=[str(x) for x in (export.get("formats") or ["csv"])],
            bundle_visibility=str(export.get("bundle_visibility") or "public_only"),
            freshness_hours=float(raw.get("freshness_hours", 24)),
        )


@dataclass
class AssertionResult:
    name: str
    expected: Any
    actual: Any
    passed: bool
    detail: str = ""


@dataclass
class CaseResult:
    id: str
    category: str
    status: Literal["pass", "fail", "error"]
    message: str
    assertions: list[AssertionResult] = field(default_factory=list)
    answer_preview: str = ""
    trace_id: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    latency_ms: int | None = None
    retrieval_chunk_ids: list[str] = field(default_factory=list)
    no_context: bool | None = None
    requires_human: bool | None = None
    escalation_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "status": self.status,
            "message": self.message,
            "assertions": [
                {
                    "name": a.name,
                    "expected": a.expected,
                    "actual": a.actual,
                    "pass": a.passed,
                    "detail": a.detail,
                }
                for a in self.assertions
            ],
            "answer_preview": self.answer_preview,
            "trace_id": self.trace_id,
            "sources": self.sources,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "retrieval_chunk_ids": self.retrieval_chunk_ids,
            "no_context": self.no_context,
            "requires_human": self.requires_human,
            "escalation_type": self.escalation_type,
        }


@dataclass
class CategorySummary:
    total: int
    passed: int
    pass_rate: float
    threshold: float
    status: Literal["pass", "fail", "missing"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "pass_rate": self.pass_rate,
            "threshold": self.threshold,
            "status": self.status,
        }


@dataclass
class EvalReport:
    run_id: str
    client_id: str
    status: Literal["pass", "fail"]
    evaluated_index_version: str | None
    evaluated_at: str
    categories: dict[str, CategorySummary]
    regulated_mode: bool
    citation_tests_required: bool
    citation_tests_present: bool
    citation_tests_passed: bool
    deploy_eligible: bool
    report_path: str
    failure_reasons: list[str] = field(default_factory=list)
    failed_cases: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "client_id": self.client_id,
            "status": self.status,
            "evaluated_index_version": self.evaluated_index_version,
            "evaluated_at": self.evaluated_at,
            "categories": {k: v.to_dict() for k, v in self.categories.items()},
            "regulated": {
                "regulated_mode": self.regulated_mode,
                "citation_tests_required": self.citation_tests_required,
                "citation_tests_present": self.citation_tests_present,
                "citation_tests_passed": self.citation_tests_passed,
            },
            "deploy_eligible": self.deploy_eligible,
            "report_path": self.report_path,
            "failure_reasons": self.failure_reasons,
            "failed_cases": self.failed_cases,
        }
