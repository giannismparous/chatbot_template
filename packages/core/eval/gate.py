from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from packages.core.config.loader import TenantConfigLoader
from packages.core.eval.loader import load_eval_suite
from packages.core.eval.models import EvalReport
from packages.core.eval.paths import latest_eval_report_path
from packages.core.eval.requirements import resolve_eval_requirements
from packages.core.ingestion.manifest import read_active_manifest
from packages.core.ingestion.paths import active_manifest_path


DeployGateReason = Literal[
    "ok",
    "no_eval_report",
    "eval_failed",
    "eval_stale_index",
    "eval_expired",
    "eval_version_mismatch",
    "regulated_missing_citation_tests",
    "regulated_citation_fail",
    "no_pending_version",
    "regulated_skip_gate_forbidden",
]


@dataclass
class DeployGateResult:
    allowed: bool
    reason: DeployGateReason
    detail: str
    report: EvalReport | None = None


def load_eval_report_dict(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid eval report JSON")
    return data


def dict_to_eval_report(data: dict) -> EvalReport:
    from packages.core.eval.models import CategorySummary

    categories = {}
    for name, raw in (data.get("categories") or {}).items():
        categories[name] = CategorySummary(
            total=int(raw.get("total", 0)),
            passed=int(raw.get("passed", 0)),
            pass_rate=float(raw.get("pass_rate", 0)),
            threshold=float(raw.get("threshold", 1)),
            status=raw.get("status", "fail"),
        )
    regulated = data.get("regulated") or {}
    return EvalReport(
        run_id=str(data.get("run_id") or ""),
        client_id=str(data.get("client_id") or ""),
        status=data.get("status", "fail"),
        evaluated_index_version=data.get("evaluated_index_version"),
        evaluated_at=str(data.get("evaluated_at") or ""),
        categories=categories,
        regulated_mode=bool(regulated.get("regulated_mode")),
        citation_tests_required=bool(regulated.get("citation_tests_required")),
        citation_tests_present=bool(regulated.get("citation_tests_present")),
        citation_tests_passed=bool(regulated.get("citation_tests_passed")),
        deploy_eligible=bool(data.get("deploy_eligible")),
        report_path=str(data.get("report_path") or ""),
        failure_reasons=list(data.get("failure_reasons") or []),
        failed_cases=list(data.get("failed_cases") or []),
    )


def check_deploy_gate(
    *,
    clients_root: Path,
    client_id: str,
    config_loader: TenantConfigLoader,
    report_path: Path | None = None,
    freshness_hours: float | None = None,
) -> DeployGateResult:
    manifest = read_active_manifest(active_manifest_path(clients_root, client_id))
    if not manifest.pending:
        return DeployGateResult(False, "no_pending_version", "No pending index version to deploy")

    from packages.core.storage.tenant_cache_hydrator import ensure_firebase_eval_assets_hydrated

    ensure_firebase_eval_assets_hydrated(client_id=client_id)
    merged = config_loader.load(client_id)
    regulated_mode = bool((merged.client or {}).get("regulated_mode", False))
    suite = load_eval_suite(clients_root, client_id)
    eval_requirements = resolve_eval_requirements(
        suite=suite,
        regulated_mode=regulated_mode,
        merged=merged,
    )
    ttl = freshness_hours if freshness_hours is not None else suite.freshness_hours

    path = report_path or latest_eval_report_path(clients_root, client_id)
    if not path.is_file():
        return DeployGateResult(False, "no_eval_report", f"Missing eval report: {path}")

    data = load_eval_report_dict(path)
    report = dict_to_eval_report(data)

    if report.evaluated_index_version != manifest.pending:
        return DeployGateResult(
            False,
            "eval_version_mismatch",
            f"Report version {report.evaluated_index_version!r} != pending {manifest.pending!r}",
            report,
        )

    if report.evaluated_at:
        evaluated_at = datetime.fromisoformat(report.evaluated_at)
        if evaluated_at.tzinfo is None:
            evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - evaluated_at > timedelta(hours=ttl):
            return DeployGateResult(False, "eval_expired", f"Eval older than {ttl}h", report)

    if eval_requirements.citation_tests_required:
        if not report.citation_tests_present:
            return DeployGateResult(
                False,
                "regulated_missing_citation_tests",
                "Regulated client requires citation_source tests",
                report,
            )
        if not report.citation_tests_passed:
            return DeployGateResult(
                False,
                "regulated_citation_fail",
                "Citation tests did not pass",
                report,
            )

    if report.status != "pass" or not report.deploy_eligible:
        return DeployGateResult(False, "eval_failed", "Eval report status is fail", report)

    return DeployGateResult(True, "ok", "Deploy gate passed", report)


def assert_skip_gate_allowed(*, clients_root: Path, client_id: str, config_loader: TenantConfigLoader) -> None:
    merged = config_loader.load(client_id)
    if bool((merged.client or {}).get("regulated_mode", False)):
        raise PermissionError("regulated_skip_gate_forbidden: regulated clients cannot bypass deploy gate")
