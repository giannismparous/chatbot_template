from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from packages.core.eval.export import export_reviewer_csv, export_reviewer_xlsx
from packages.core.eval.bundle import build_cited_doc_bundle
from packages.core.eval.models import (
    CaseResult,
    CategorySummary,
    EvalReport,
    EvalSuiteConfig,
)
from packages.core.eval.requirements import EvalRequirements
from packages.core.ingestion.manifest import utc_now_iso


def eval_job_exit_code(report: EvalReport) -> int:
    """Process exit code for eval worker jobs: 0 only when pass and deploy-eligible."""
    return 0 if report.status == "pass" and report.deploy_eligible else 1


def build_eval_report(
    *,
    run_id: str,
    client_id: str,
    suite: EvalSuiteConfig,
    case_results: list[CaseResult],
    regulated_mode: bool,
    evaluated_index_version: str | None,
    report_path: str,
    eval_requirements: EvalRequirements | None = None,
) -> EvalReport:
    reqs = eval_requirements or EvalRequirements(
        required_categories=list(suite.required_categories),
        citation_tests_required=bool(regulated_mode and suite.require_citation_tests),
        placeholder=bool(suite.placeholder),
    )
    categories = _summarize_categories(case_results, suite, reqs)
    citation_present = any(c.category == "citation_source" for c in case_results)
    citation_passed = categories.get("citation_source", CategorySummary(0, 0, 0, 1, "missing")).status == "pass"

    failure_reasons: list[str] = []
    deploy_eligible = True

    if reqs.placeholder:
        deploy_eligible = False
        failure_reasons.append("placeholder_suite:customize eval cases before deploy")

    for cat_name, summary in categories.items():
        if cat_name in reqs.required_categories and summary.status != "pass":
            deploy_eligible = False
            failure_reasons.append(f"category_fail:{cat_name}")

    if reqs.citation_tests_required:
        if not citation_present:
            deploy_eligible = False
            failure_reasons.append("regulated_missing_citation_tests")
        elif not citation_passed:
            deploy_eligible = False
            failure_reasons.append("regulated_citation_fail")

    overall_pass = deploy_eligible and all(
        categories.get(cat, CategorySummary(0, 0, 0, 1, "missing")).status == "pass"
        for cat in reqs.required_categories
        if categories.get(cat) and categories[cat].total > 0
    )

    return EvalReport(
        run_id=run_id,
        client_id=client_id,
        status="pass" if overall_pass and deploy_eligible else "fail",
        evaluated_index_version=evaluated_index_version,
        evaluated_at=utc_now_iso(),
        categories=categories,
        regulated_mode=regulated_mode,
        citation_tests_required=reqs.citation_tests_required,
        citation_tests_present=citation_present,
        citation_tests_passed=citation_passed,
        deploy_eligible=deploy_eligible and overall_pass,
        report_path=report_path,
        failure_reasons=failure_reasons,
        failed_cases=_failed_case_summaries(case_results),
    )


def _failed_case_summaries(case_results: list[CaseResult]) -> list[dict]:
    summaries: list[dict] = []
    for case in case_results:
        if case.status == "pass":
            continue
        failed_assertions = [
            {
                "name": assertion.name,
                "expected": assertion.expected,
                "actual": str(assertion.actual)[:160],
            }
            for assertion in case.assertions
            if not assertion.passed
        ]
        summaries.append(
            {
                "id": case.id,
                "category": case.category,
                "status": case.status,
                "message": case.message,
                "failed_assertions": failed_assertions,
                "answer_preview": (case.answer_preview or "")[:200],
                "error": case.error,
            }
        )
    return summaries


def write_eval_artifacts(
    *,
    run_dir: Path,
    run_payload: dict,
    report: EvalReport,
    clients_root: Path,
    export_formats: list[str],
    allow_internal_bundle: bool,
    bundle_visibility: str,
    index_version: str | None,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "eval_run.json").write_text(
        json.dumps(run_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (run_dir / "eval_report.json").write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    reviewer_dir = run_dir / "reviewer"
    reviewer_dir.mkdir(parents=True, exist_ok=True)
    cases = run_payload.get("cases") or []
    if "csv" in export_formats:
        export_reviewer_csv(reviewer_dir / "reviewer_export.csv", cases, report)
    if "xlsx" in export_formats:
        export_reviewer_xlsx(reviewer_dir / "reviewer_export.xlsx", cases, report)
    if bundle_visibility == "public_only" or allow_internal_bundle:
        build_cited_doc_bundle(
            reviewer_dir / f"cited_docs_{report.run_id}.zip",
            clients_root=clients_root,
            client_id=report.client_id,
            cases=cases,
            index_version=index_version,
            public_only=not allow_internal_bundle,
        )


def _summarize_categories(
    case_results: list[CaseResult],
    suite: EvalSuiteConfig,
    reqs: EvalRequirements,
) -> dict[str, CategorySummary]:
    grouped: dict[str, list[CaseResult]] = {}
    for result in case_results:
        grouped.setdefault(result.category, []).append(result)

    required = set(reqs.required_categories)
    if reqs.citation_tests_required:
        required.add("citation_source")

    summaries: dict[str, CategorySummary] = {}
    for cat in sorted(required | set(grouped.keys())):
        items = grouped.get(cat, [])
        if not items:
            summaries[cat] = CategorySummary(
                total=0,
                passed=0,
                pass_rate=0.0,
                threshold=_threshold_for(cat, suite),
                status="missing" if cat in required else "pass",
            )
            continue
        passed = sum(1 for i in items if i.status == "pass")
        total = len(items)
        rate = passed / total if total else 0.0
        threshold = _threshold_for(cat, suite)
        summaries[cat] = CategorySummary(
            total=total,
            passed=passed,
            pass_rate=round(rate, 4),
            threshold=threshold,
            status="pass" if rate >= threshold and passed == total else "fail",
        )
    return summaries


def _threshold_for(category: str, suite: EvalSuiteConfig) -> float:
    if category == "retrieval":
        return suite.thresholds["retrieval_min_pass_rate"]
    if category == "answer":
        return suite.thresholds["answer_min_pass_rate"]
    if category.startswith("safety_"):
        return suite.thresholds["safety_min_pass_rate"]
    if category == "citation_source":
        return suite.thresholds["citation_min_pass_rate"]
    return suite.thresholds["overall_min_pass_rate"]
