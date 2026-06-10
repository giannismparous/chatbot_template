from __future__ import annotations

from pathlib import Path

from packages.adapters.cloudrun.jobs_dispatcher import build_cloud_run_jobs_dispatcher
from packages.core.pipeline.orchestrator import PipelineOrchestrator
from packages.core.stack.factory import Stack


def build_pipeline_orchestrator(
    *,
    stack: Stack,
    clients_root: Path | None = None,
) -> PipelineOrchestrator:
    root = clients_root or stack.config_store.get_clients_root()
    return PipelineOrchestrator(
        pipeline_store=stack.pipeline_store,
        job_runner=stack.job_runner,
        clients_root=root,
        file_store=stack.file_store,
        jobs_dispatcher=build_cloud_run_jobs_dispatcher(),
    )
