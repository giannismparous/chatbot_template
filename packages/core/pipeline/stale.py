from __future__ import annotations

import os

from packages.core.pipeline.models import PipelineRunRecord, PipelineStatus, utc_now


def pipeline_stale_timeout_seconds() -> int:
    raw = os.getenv("PIPELINE_STALE_TIMEOUT_SECONDS", "7200").strip()
    try:
        return max(60, int(raw))
    except ValueError:
        return 7200


def is_pipeline_stale(record: PipelineRunRecord) -> bool:
    if record.status != PipelineStatus.RUNNING:
        return False
    age = (utc_now() - record.updated_at).total_seconds()
    return age > pipeline_stale_timeout_seconds()


def mark_pipeline_stale(record: PipelineRunRecord) -> PipelineRunRecord:
    record.status = PipelineStatus.STALE
    record.finished_at = utc_now()
    record.error = (
        f"Pipeline stale: no progress for {pipeline_stale_timeout_seconds()}s "
        f"(last updated {record.updated_at.isoformat()})."
    )
    record.current_step = None
    return record
