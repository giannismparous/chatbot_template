from __future__ import annotations

import os

from packages.core.pipeline.models import PipelineStep

_DEFAULT_SECONDS: dict[PipelineStep, int] = {
    PipelineStep.DRIVE_SYNC: 7200,
    PipelineStep.INGEST: 7200,
    PipelineStep.EVAL: 3600,
    PipelineStep.DEPLOY: 1800,
}

_ENV_KEYS: dict[PipelineStep, str] = {
    PipelineStep.DRIVE_SYNC: "PIPELINE_TIMEOUT_DRIVE_SYNC",
    PipelineStep.INGEST: "PIPELINE_TIMEOUT_INGEST",
    PipelineStep.EVAL: "PIPELINE_TIMEOUT_EVAL",
    PipelineStep.DEPLOY: "PIPELINE_TIMEOUT_DEPLOY",
}


def step_timeout_seconds(step: PipelineStep) -> int:
    env_key = _ENV_KEYS[step]
    raw = os.getenv(env_key, str(_DEFAULT_SECONDS[step])).strip()
    try:
        return max(60, int(raw))
    except ValueError:
        return _DEFAULT_SECONDS[step]
