from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.dependencies.admin_services import clients_root, get_job_runner
from apps.api.dependencies.auth import require_admin_token
from apps.api.schemas_admin import (
    CrawlJobRequest,
    DriveSyncJobRequest,
    DeployConflictResponse,
    DeployRequest,
    DeployResponse,
    EvalJobRequest,
    EvalSummaryDTO,
    IndexStatusDTO,
    JobAcceptedDTO,
    JobStatusDTO,
    MetricsSummaryDTO,
    RollbackResponse,
)
from apps.worker.jobs.deploy_index import deploy_index
from apps.worker.jobs.rollback_index import rollback_index
from packages.core.jobs.local_runner import LocalJobRunner
from packages.core.admin.roles import AdminContext
from packages.core.config.loader import TenantConfigLoader
from packages.core.eval.gate import check_deploy_gate
from packages.core.eval.paths import latest_eval_report_path
from packages.core.ingestion.manifest import read_active_manifest
from packages.core.ingestion.paths import active_manifest_path
from packages.core.jobs.models import JobType
from packages.core.stack.factory import project_root
from packages.core.tenant.paths import safe_client_id

router = APIRouter(
    prefix="/v1/admin/clients",
    tags=["admin-client-jobs"],
    dependencies=[Depends(require_admin_token)],
)


def _job_dto(record) -> JobStatusDTO:
    return JobStatusDTO(
        job_id=record.job_id,
        client_id=record.client_id,
        job_type=record.job_type.value,
        status=record.status.value,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
        result=record.result,
        error=record.error,
    )


@router.post("/{client_id}/jobs/ingest", response_model=JobAcceptedDTO, status_code=status.HTTP_202_ACCEPTED)
def trigger_ingest(
    client_id: str,
    admin: AdminContext = Depends(require_admin_token),
    jobs: LocalJobRunner = Depends(get_job_runner),
) -> JobAcceptedDTO:
    _ = admin
    root = clients_root()

    def _run() -> dict:
        from packages.core.config.loader import TenantConfigLoader
        from packages.core.ingestion.pipeline import ingest_client_uploads

        loader = TenantConfigLoader(
            clients_root=root,
            domain_packs_root=project_root() / "packages" / "domain_packs",
        )
        result = ingest_client_uploads(
            clients_root=root,
            client_id=client_id,
            config_loader=loader,
        )
        return {
            "version_id": result.version_id,
            "chunk_count": result.chunk_count,
            "source_count": result.source_count,
        }

    record = jobs.submit(client_id=client_id, job_type=JobType.INGEST, runner=_run)
    return JobAcceptedDTO(job_id=record.job_id, job_type=record.job_type.value, status=record.status.value)


@router.post("/{client_id}/jobs/crawl", response_model=JobAcceptedDTO, status_code=status.HTTP_202_ACCEPTED)
def trigger_crawl(
    client_id: str,
    payload: CrawlJobRequest,
    admin: AdminContext = Depends(require_admin_token),
    jobs: LocalJobRunner = Depends(get_job_runner),
) -> JobAcceptedDTO:
    _ = admin
    root = clients_root()

    def _run() -> dict:
        from packages.core.config.loader import TenantConfigLoader
        from packages.core.web_sources.service import crawl_client_web_sources

        loader = TenantConfigLoader(
            clients_root=root,
            domain_packs_root=project_root() / "packages" / "domain_packs",
        )
        return crawl_client_web_sources(
            clients_root=root,
            client_id=client_id,
            config_loader=loader,
            source_ids=payload.source_ids,
        )

    record = jobs.submit(client_id=client_id, job_type=JobType.CRAWL, runner=_run)
    return JobAcceptedDTO(job_id=record.job_id, job_type=record.job_type.value, status=record.status.value)


@router.post("/{client_id}/jobs/drive-sync", response_model=JobAcceptedDTO, status_code=status.HTTP_202_ACCEPTED)
def trigger_drive_sync(
    client_id: str,
    payload: DriveSyncJobRequest,
    admin: AdminContext = Depends(require_admin_token),
    jobs: LocalJobRunner = Depends(get_job_runner),
) -> JobAcceptedDTO:
    _ = admin
    root = clients_root()

    def _run() -> dict:
        from packages.core.config.loader import TenantConfigLoader
        from packages.core.drive_sources.service import sync_client_drive_sources

        loader = TenantConfigLoader(
            clients_root=root,
            domain_packs_root=project_root() / "packages" / "domain_packs",
        )
        return sync_client_drive_sources(
            clients_root=root,
            client_id=client_id,
            config_loader=loader,
            source_ids=payload.source_ids,
        )

    record = jobs.submit(client_id=client_id, job_type=JobType.DRIVE_SYNC, runner=_run)
    return JobAcceptedDTO(job_id=record.job_id, job_type=record.job_type.value, status=record.status.value)


@router.post("/{client_id}/jobs/eval", response_model=JobAcceptedDTO, status_code=status.HTTP_202_ACCEPTED)
def trigger_eval(
    client_id: str,
    payload: EvalJobRequest,
    admin: AdminContext = Depends(require_admin_token),
    jobs: LocalJobRunner = Depends(get_job_runner),
) -> JobAcceptedDTO:
    _ = admin
    root = clients_root()

    def _run() -> dict:
        from packages.core.eval.runner import run_eval

        report, run_dir = run_eval(
            clients_root=root,
            client_id=client_id,
            suite_filter=payload.suite,
            llm_mode=payload.llm_mode,
        )
        return {
            "run_id": report.run_id,
            "status": report.status,
            "report_path": str(run_dir / "eval_report.json"),
            "deploy_eligible": report.deploy_eligible,
        }

    record = jobs.submit(client_id=client_id, job_type=JobType.EVAL, runner=_run)
    return JobAcceptedDTO(job_id=record.job_id, job_type=record.job_type.value, status=record.status.value)


@router.get("/{client_id}/jobs", response_model=list[JobStatusDTO])
def list_jobs(
    client_id: str,
    admin: AdminContext = Depends(require_admin_token),
    jobs: LocalJobRunner = Depends(get_job_runner),
) -> list[JobStatusDTO]:
    _ = admin
    return [_job_dto(r) for r in jobs.list_jobs(client_id)]


@router.get("/{client_id}/jobs/{job_id}", response_model=JobStatusDTO)
def get_job(
    client_id: str,
    job_id: str,
    admin: AdminContext = Depends(require_admin_token),
    jobs: LocalJobRunner = Depends(get_job_runner),
) -> JobStatusDTO:
    _ = admin
    record = jobs.get_job(client_id, job_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return _job_dto(record)


@router.post("/{client_id}/deploy", response_model=DeployResponse)
def deploy_client_index(
    client_id: str,
    _payload: DeployRequest,
    admin: AdminContext = Depends(require_admin_token),
) -> DeployResponse:
    _ = admin
    _ = _payload
    cid = safe_client_id(client_id)
    root = clients_root()
    loader = TenantConfigLoader(
        clients_root=root,
        domain_packs_root=project_root() / "packages" / "domain_packs",
    )
    gate = check_deploy_gate(clients_root=root, client_id=cid, config_loader=loader)
    if not gate.allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DeployConflictResponse(reason=gate.reason, detail=gate.detail).model_dump(),
        )
    try:
        activated = deploy_index(clients_root=root, client_id=cid)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DeployConflictResponse(reason="eval_failed", detail=str(exc)).model_dump(),
        ) from exc
    eval_run_id = gate.report.run_id if gate.report else None
    return DeployResponse(status="ok", activated_version=activated, eval_run_id=eval_run_id)


@router.post("/{client_id}/rollback", response_model=RollbackResponse)
def rollback_client_index(
    client_id: str,
    admin: AdminContext = Depends(require_admin_token),
) -> RollbackResponse:
    _ = admin
    root = clients_root()
    try:
        active = rollback_index(clients_root=root, client_id=client_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return RollbackResponse(active_version=active)


@router.get("/{client_id}/index", response_model=IndexStatusDTO)
def get_index_status(
    client_id: str,
    admin: AdminContext = Depends(require_admin_token),
) -> IndexStatusDTO:
    _ = admin
    cid = safe_client_id(client_id)
    manifest = read_active_manifest(active_manifest_path(clients_root(), cid))
    return IndexStatusDTO(active=manifest.active, pending=manifest.pending, previous=manifest.previous)


@router.get("/{client_id}/eval/latest", response_model=EvalSummaryDTO)
def get_latest_eval(
    client_id: str,
    admin: AdminContext = Depends(require_admin_token),
) -> EvalSummaryDTO:
    _ = admin
    cid = safe_client_id(client_id)
    path = latest_eval_report_path(clients_root(), cid)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No eval report found.")
    data = json.loads(path.read_text(encoding="utf-8"))
    categories = {}
    for name, raw in (data.get("categories") or {}).items():
        if isinstance(raw, dict):
            categories[name] = {
                "total": raw.get("total"),
                "passed": raw.get("passed"),
                "pass_rate": raw.get("pass_rate"),
                "status": raw.get("status"),
            }
    return EvalSummaryDTO(
        run_id=data.get("run_id"),
        status=data.get("status"),
        evaluated_index_version=data.get("evaluated_index_version"),
        evaluated_at=data.get("evaluated_at"),
        deploy_eligible=bool(data.get("deploy_eligible")),
        categories=categories,
        failure_reasons=list(data.get("failure_reasons") or []),
        failed_cases=list(data.get("failed_cases") or []),
    )


@router.get("/{client_id}/metrics", response_model=MetricsSummaryDTO)
def get_client_metrics(
    client_id: str,
    admin: AdminContext = Depends(require_admin_token),
) -> MetricsSummaryDTO:
    _ = admin
    from apps.api.dependencies.stack import get_stack

    cid = safe_client_id(client_id)
    metrics = get_stack().metrics_store.get_client_metrics(cid)
    avg_latency = None
    if metrics.latency_ms_count > 0:
        avg_latency = metrics.latency_ms_sum / metrics.latency_ms_count
    return MetricsSummaryDTO(
        client_id=cid,
        updated_at=metrics.updated_at.isoformat(),
        total_chats=metrics.total_chats,
        no_context=metrics.no_context,
        crisis=metrics.crisis,
        input_blocked=metrics.input_blocked,
        provider_fallback=metrics.provider_fallback,
        avg_latency_ms=avg_latency,
        confidence_buckets=dict(metrics.confidence_buckets),
    )
