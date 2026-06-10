from __future__ import annotations

import traceback

from packages.core.pipeline.factory import build_pipeline_orchestrator
from packages.core.pipeline.logging_util import pipeline_log, pipeline_version_label
from packages.core.pipeline.models import PipelineStatus
from packages.core.stack.factory import build_stack


def run_pipeline(*, client_id: str, pipeline_id: str) -> int:
    pipeline_log(f"runner start {pipeline_version_label()}")
    pipeline_log(f"runner args client_id={client_id} pipeline_id={pipeline_id}")
    try:
        stack = build_stack()
        pipeline_log(
            f"stack profile={getattr(stack, 'profile', 'unknown')} "
            f"clients_root={stack.config_store.get_clients_root()}"
        )
        orchestrator = build_pipeline_orchestrator(stack=stack)
        record = orchestrator.get(client_id, pipeline_id)
        if record is None:
            pipeline_log(f"pipeline record not found: {pipeline_id}")
            return 1
        pipeline_log(
            f"loaded pipeline status={record.status.value} steps={record.steps} "
            f"preset={record.preset} runner_execution={record.runner_execution}"
        )
        final = orchestrator.execute_pipeline(client_id=client_id, pipeline_id=pipeline_id)
        pipeline_log(
            f"runner finished status={final.status.value} step_results={len(final.step_results)} "
            f"error={final.error!r}"
        )
        if final.ingest_summary:
            pipeline_log(f"ingest_summary={final.ingest_summary}")
        if final.eval_summary:
            pipeline_log(f"eval_summary={final.eval_summary}")
        if final.status == PipelineStatus.SUCCEEDED:
            return 0
        return 1
    except Exception as exc:
        pipeline_log(f"runner fatal error: {exc}")
        traceback.print_exc()
        return 1
