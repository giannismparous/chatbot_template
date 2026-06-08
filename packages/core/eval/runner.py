from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Literal

from packages.core.config.loader import TenantConfigLoader
from packages.core.domain.models import ChatMessage, ChatRequest
from packages.core.eval.assertions import all_passed, evaluate_chat, evaluate_retrieval
from packages.core.eval.index_scope import eval_index_scope
from packages.core.eval.loader import load_eval_cases, load_eval_suite
from packages.core.eval.models import CaseResult, CategorySummary, EvalCase, EvalReport, EvalSuiteConfig
from packages.core.eval.paths import eval_run_dir, latest_eval_report_path
from packages.core.eval.report import build_eval_report, write_eval_artifacts
from packages.core.eval.requirements import resolve_eval_requirements
from packages.core.eval.runtime import ReplayLLMProvider, build_eval_orchestrator
from packages.core.ingestion.manifest import utc_now_iso
from packages.core.stack.factory import project_root
from packages.core.tenant.paths import safe_client_id


def run_eval(
    *,
    clients_root: Path,
    client_id: str,
    suite_filter: str = "full",
    llm_mode: str = "live",
    replay_llm: ReplayLLMProvider | None = None,
    output_dir: Path | None = None,
    export_formats: list[str] | None = None,
    allow_internal_bundle: bool = False,
) -> tuple[EvalReport, Path]:
    cid = safe_client_id(client_id)
    from packages.core.storage.tenant_cache_hydrator import ensure_firebase_eval_assets_hydrated

    ensure_firebase_eval_assets_hydrated(client_id=cid)
    config_loader = TenantConfigLoader(
        clients_root=clients_root,
        domain_packs_root=project_root() / "packages" / "domain_packs",
    )
    suite = load_eval_suite(clients_root, cid)
    cases = _filter_cases(load_eval_cases(clients_root, cid), suite_filter)
    merged = config_loader.load(cid)
    regulated_mode = bool((merged.client or {}).get("regulated_mode", False))
    eval_requirements = resolve_eval_requirements(
        suite=suite,
        regulated_mode=regulated_mode,
        merged=merged,
    )

    run_id = f"eval_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = output_dir or eval_run_dir(clients_root, cid, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    with eval_index_scope(clients_root, cid, scope=suite.index_scope) as scope:
        orchestrator = build_eval_orchestrator(
            clients_root=clients_root,
            config_loader=config_loader,
            llm_mode=llm_mode,
            replay_llm=replay_llm,
        )
        retriever = orchestrator._retriever  # production wiring
        case_results: list[CaseResult] = []
        for case in cases:
            case_results.append(
                _run_case(
                    case=case,
                    client_id=cid,
                    suite=suite,
                    orchestrator=orchestrator,
                    retriever=retriever,
                )
            )

    started_at = utc_now_iso()
    finished_at = utc_now_iso()
    run_payload = {
        "run_id": run_id,
        "client_id": cid,
        "started_at": started_at,
        "finished_at": finished_at,
        "target_index_version": scope.version_id,
        "target_index_scope": suite.index_scope,
        "llm_mode": llm_mode,
        "suite_filter": suite_filter,
        "cases": [c.to_dict() for c in case_results],
    }
    report = build_eval_report(
        run_id=run_id,
        client_id=cid,
        suite=suite,
        case_results=case_results,
        regulated_mode=regulated_mode,
        evaluated_index_version=scope.version_id,
        report_path=str(run_dir / "eval_report.json"),
        eval_requirements=eval_requirements,
    )
    formats = export_formats if export_formats is not None else suite.export_formats
    write_eval_artifacts(
        run_dir=run_dir,
        run_payload=run_payload,
        report=report,
        clients_root=clients_root,
        export_formats=formats,
        allow_internal_bundle=allow_internal_bundle,
        bundle_visibility=suite.bundle_visibility,
        index_version=scope.version_id,
    )
    latest_path = latest_eval_report_path(clients_root, cid)
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    from packages.core.storage.eval_output_sync import persist_eval_output_if_firebase

    persist_eval_output_if_firebase(
        client_id=cid,
        clients_root=clients_root,
        run_dir=run_dir,
        latest_path=latest_path,
    )
    return report, run_dir


def _filter_cases(cases: list[EvalCase], suite_filter: str) -> list[EvalCase]:
    if suite_filter == "full":
        return cases
    if suite_filter == "retrieval":
        return [c for c in cases if c.category == "retrieval"]
    if suite_filter == "answer":
        return [c for c in cases if c.category == "answer"]
    if suite_filter == "safety":
        return [c for c in cases if c.category.startswith("safety_")]
    if suite_filter == "citation":
        return [c for c in cases if c.category == "citation_source"]
    if suite_filter == "reviewer":
        return [c for c in cases if c.category in {"answer", "citation_source"}]
    raise ValueError(f"Unknown suite filter: {suite_filter}")


def _run_case(
    *,
    case: EvalCase,
    client_id: str,
    suite: EvalSuiteConfig,
    orchestrator,
    retriever,
) -> CaseResult:
    mode = case.mode or suite.default_mode
    try:
        if case.category == "retrieval":
            started = perf_counter()
            outcome = retriever.retrieve_with_outcome(
                case.message,
                limit=case.top_k,
                mode=mode,
                client_id=client_id,
            )
            assertions = evaluate_retrieval(case.expect, outcome)
            passed = all_passed(assertions)
            return CaseResult(
                id=case.id,
                category=case.category,
                status="pass" if passed else "fail",
                message=case.message,
                assertions=assertions,
                latency_ms=int((perf_counter() - started) * 1000),
                retrieval_chunk_ids=[c.id for c in outcome.chunks],
                no_context=outcome.no_context,
            )

        started = perf_counter()
        response = orchestrator.answer(
            ChatRequest(
                client_id=client_id,
                message=case.message,
                history=[ChatMessage(role=h["role"], content=h["content"]) for h in case.history],
                mode=mode,
                top_k=case.top_k,
            )
        )
        assertions = evaluate_chat(case.expect, response)
        passed = all_passed(assertions)
        return CaseResult(
            id=case.id,
            category=case.category,
            status="pass" if passed else "fail",
            message=case.message,
            assertions=assertions,
            answer_preview=(response.answer or "")[:500],
            trace_id=response.trace_id,
            sources=[
                {"index": s.index, "title": s.title, "url": s.url, "score": s.score}
                for s in response.sources
            ],
            latency_ms=int((perf_counter() - started) * 1000),
            no_context=bool(response.trace.get("no_context")),
            requires_human=response.requires_human,
            escalation_type=response.escalation.type if response.escalation else None,
        )
    except Exception as exc:
        return CaseResult(
            id=case.id,
            category=case.category,
            status="error",
            message=case.message,
            error=str(exc),
        )
