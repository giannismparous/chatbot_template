from __future__ import annotations

from apps.api.dependencies.admin_services import clients_root
from apps.api.dependencies.stack import get_stack
from packages.adapters.cloudrun.jobs_dispatcher import build_cloud_run_jobs_dispatcher
from packages.core.pipeline.orchestrator import PipelineOrchestrator


def get_pipeline_orchestrator() -> PipelineOrchestrator:
    stack = get_stack()
    dispatcher = build_cloud_run_jobs_dispatcher()
    return PipelineOrchestrator(
        pipeline_store=stack.pipeline_store,
        job_runner=stack.job_runner,
        clients_root=clients_root(),
        file_store=stack.file_store,
        jobs_dispatcher=dispatcher,
    )
