from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.dependencies.auth import require_admin_token
from apps.api.dependencies.pipeline_services import get_pipeline_orchestrator
from apps.api.schemas_admin import (
    PipelineRunAcceptedDTO,
    PipelineRunDTO,
    PipelineRunRequest,
    PipelineStepResultDTO,
)
from packages.core.admin.roles import AdminContext
from packages.core.pipeline.models import PipelineRunRecord
from packages.core.tenant.paths import safe_client_id

router = APIRouter(
    prefix="/v1/admin/clients",
    tags=["admin-client-pipeline"],
    dependencies=[Depends(require_admin_token)],
)


def _pipeline_dto(record: PipelineRunRecord) -> PipelineRunDTO:
    return PipelineRunDTO(
        pipeline_id=record.pipeline_id,
        client_id=record.client_id,
        status=record.status.value,
        preset=record.preset,
        steps=record.steps,
        current_step=record.current_step,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
        started_at=record.started_at.isoformat() if record.started_at else None,
        finished_at=record.finished_at.isoformat() if record.finished_at else None,
        active_version_before=record.active_version_before,
        pending_version_after_ingest=record.pending_version_after_ingest,
        active_version_after_deploy=record.active_version_after_deploy,
        step_results=[
            PipelineStepResultDTO(
                step=item.step,
                status=item.status,
                job_id=item.job_id,
                cloud_run_execution=item.cloud_run_execution,
                result=item.result,
                error=item.error,
            )
            for item in record.step_results
        ],
        ingest_summary=record.ingest_summary,
        eval_summary=record.eval_summary,
        index_manifest=record.index_manifest,
        force_empty_deploy=record.force_empty_deploy,
        eval_llm_mode=record.eval_llm_mode,
        error=record.error,
        runtime_refresh_note=record.runtime_refresh_note,
    )


@router.post("/{client_id}/pipeline/run", response_model=PipelineRunAcceptedDTO, status_code=status.HTTP_202_ACCEPTED)
def run_client_pipeline(
    client_id: str,
    payload: PipelineRunRequest,
    admin: AdminContext = Depends(require_admin_token),
) -> PipelineRunAcceptedDTO:
    _ = admin
    cid = safe_client_id(client_id)
    orchestrator = get_pipeline_orchestrator()
    try:
        record = orchestrator.start(
            client_id=cid,
            preset=payload.preset,
            steps=payload.steps,
            eval_llm_mode=payload.eval_llm_mode,
            eval_suite=payload.eval_suite,
            force_empty_deploy=payload.force_empty_deploy,
            drive_source_ids=payload.drive_source_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PipelineRunAcceptedDTO(
        pipeline_id=record.pipeline_id,
        client_id=record.client_id,
        status=record.status.value,
        preset=record.preset,
        steps=record.steps,
    )


@router.get("/{client_id}/pipeline/status/{pipeline_id}", response_model=PipelineRunDTO)
def get_pipeline_status(
    client_id: str,
    pipeline_id: str,
    admin: AdminContext = Depends(require_admin_token),
) -> PipelineRunDTO:
    _ = admin
    cid = safe_client_id(client_id)
    record = get_pipeline_orchestrator().get(cid, pipeline_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline run not found.")
    return _pipeline_dto(record)


@router.get("/{client_id}/pipeline/runs", response_model=list[PipelineRunDTO])
def list_pipeline_runs(
    client_id: str,
    admin: AdminContext = Depends(require_admin_token),
) -> list[PipelineRunDTO]:
    _ = admin
    cid = safe_client_id(client_id)
    records = get_pipeline_orchestrator().list_runs(cid, limit=20)
    return [_pipeline_dto(record) for record in records]
