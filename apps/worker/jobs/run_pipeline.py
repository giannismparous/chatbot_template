from __future__ import annotations

from packages.core.pipeline.factory import build_pipeline_orchestrator
from packages.core.pipeline.models import PipelineStatus
from packages.core.stack.factory import build_stack


def run_pipeline(*, client_id: str, pipeline_id: str) -> int:
    stack = build_stack()
    orchestrator = build_pipeline_orchestrator(stack=stack)
    record = orchestrator.execute_pipeline(client_id=client_id, pipeline_id=pipeline_id)
    if record.status == PipelineStatus.SUCCEEDED:
        return 0
    return 1
