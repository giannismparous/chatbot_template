from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class PipelineStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STALE = "stale"


class PipelineStep(str, Enum):
    DRIVE_SYNC = "drive-sync"
    INGEST = "ingest"
    EVAL = "eval"
    DEPLOY = "deploy"


PIPELINE_PRESETS: dict[str, list[PipelineStep]] = {
    "sync_only": [PipelineStep.DRIVE_SYNC],
    "ingest_eval": [PipelineStep.INGEST, PipelineStep.EVAL],
    "full_deploy": [
        PipelineStep.DRIVE_SYNC,
        PipelineStep.INGEST,
        PipelineStep.EVAL,
        PipelineStep.DEPLOY,
    ],
}


def resolve_pipeline_steps(
    *,
    preset: str | None,
    steps: list[str] | None,
) -> list[PipelineStep]:
    if steps:
        return [PipelineStep(step) for step in steps]
    if preset:
        resolved = PIPELINE_PRESETS.get(preset.strip())
        if resolved is None:
            raise ValueError(f"Unknown pipeline preset: {preset!r}")
        return list(resolved)
    return list(PIPELINE_PRESETS["full_deploy"])


@dataclass
class PipelineStepResult:
    step: str
    status: str
    job_id: str | None = None
    cloud_run_execution: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "status": self.status,
            "job_id": self.job_id,
            "cloud_run_execution": self.cloud_run_execution,
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineStepResult:
        return cls(
            step=str(data.get("step") or ""),
            status=str(data.get("status") or ""),
            job_id=data.get("job_id"),
            cloud_run_execution=data.get("cloud_run_execution"),
            result=dict(data.get("result") or {}),
            error=data.get("error"),
        )


@dataclass
class PipelineRunRecord:
    pipeline_id: str
    client_id: str
    status: PipelineStatus
    preset: str | None
    steps: list[str]
    current_step: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    active_version_before: str | None = None
    pending_version_after_ingest: str | None = None
    active_version_after_deploy: str | None = None
    step_results: list[PipelineStepResult] = field(default_factory=list)
    ingest_summary: dict[str, Any] = field(default_factory=dict)
    eval_summary: dict[str, Any] = field(default_factory=dict)
    index_manifest: dict[str, Any] = field(default_factory=dict)
    force_empty_deploy: bool = False
    eval_llm_mode: str = "live"
    eval_suite: str = "full"
    drive_source_ids: list[str] | None = None
    runner_execution: str | None = None
    error: str | None = None
    runtime_refresh_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "client_id": self.client_id,
            "status": self.status.value,
            "preset": self.preset,
            "steps": self.steps,
            "current_step": self.current_step,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "active_version_before": self.active_version_before,
            "pending_version_after_ingest": self.pending_version_after_ingest,
            "active_version_after_deploy": self.active_version_after_deploy,
            "step_results": [item.to_dict() for item in self.step_results],
            "ingest_summary": self.ingest_summary,
            "eval_summary": self.eval_summary,
            "index_manifest": self.index_manifest,
            "force_empty_deploy": self.force_empty_deploy,
            "eval_llm_mode": self.eval_llm_mode,
            "eval_suite": self.eval_suite,
            "drive_source_ids": self.drive_source_ids,
            "runner_execution": self.runner_execution,
            "error": self.error,
            "runtime_refresh_note": self.runtime_refresh_note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineRunRecord:
        created = _parse_dt(data.get("created_at"))
        updated = _parse_dt(data.get("updated_at"))
        started = _parse_dt(data.get("started_at")) if data.get("started_at") else None
        finished = _parse_dt(data.get("finished_at")) if data.get("finished_at") else None
        step_results = [
            PipelineStepResult.from_dict(item)
            for item in (data.get("step_results") or [])
            if isinstance(item, dict)
        ]
        return cls(
            pipeline_id=str(data["pipeline_id"]),
            client_id=str(data["client_id"]),
            status=PipelineStatus(str(data["status"])),
            preset=data.get("preset"),
            steps=[str(step) for step in (data.get("steps") or [])],
            current_step=data.get("current_step"),
            created_at=created,
            updated_at=updated,
            started_at=started,
            finished_at=finished,
            active_version_before=data.get("active_version_before"),
            pending_version_after_ingest=data.get("pending_version_after_ingest"),
            active_version_after_deploy=data.get("active_version_after_deploy"),
            step_results=step_results,
            ingest_summary=dict(data.get("ingest_summary") or {}),
            eval_summary=dict(data.get("eval_summary") or {}),
            index_manifest=dict(data.get("index_manifest") or {}),
            force_empty_deploy=bool(data.get("force_empty_deploy")),
            eval_llm_mode=str(data.get("eval_llm_mode") or "live"),
            eval_suite=str(data.get("eval_suite") or "full"),
            drive_source_ids=list(data.get("drive_source_ids") or []) or None,
            runner_execution=data.get("runner_execution"),
            error=data.get("error"),
            runtime_refresh_note=data.get("runtime_refresh_note"),
        )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime:
    dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
