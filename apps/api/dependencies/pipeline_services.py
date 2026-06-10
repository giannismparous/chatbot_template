from __future__ import annotations

from apps.api.dependencies.admin_services import clients_root
from apps.api.dependencies.stack import get_stack
from packages.core.pipeline.factory import build_pipeline_orchestrator
from packages.core.pipeline.orchestrator import PipelineOrchestrator


def get_pipeline_orchestrator() -> PipelineOrchestrator:
    return build_pipeline_orchestrator(stack=get_stack(), clients_root=clients_root())
