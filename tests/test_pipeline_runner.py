from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from packages.adapters.cloudrun.jobs_dispatcher import CloudRunJobsDispatcher, ExecutionOutcome
from packages.adapters.pipeline.local_pipeline_store import LocalPipelineStore
from packages.core.ingestion.manifest import read_active_manifest
from packages.core.ingestion.paths import active_manifest_path
from packages.core.jobs.models import JobStatus, JobType, utc_now as job_utc_now
from packages.core.storage.tenant_storage import TenantStorage
from packages.core.pipeline.models import (
    PipelineRunRecord,
    PipelineStatus,
    PipelineStep,
    utc_now,
)
from packages.core.pipeline.orchestrator import PipelineOrchestrator
from packages.core.pipeline.stale import is_pipeline_stale, mark_pipeline_stale
from tests.test_admin_lifecycle_api import _write_eval_suite, _write_passing_eval_report

ROOT = Path(__file__).resolve().parents[1]


class _FakeJobRunner:
    def __init__(self) -> None:
        self._jobs: dict[tuple[str, str], object] = {}

    def submit(self, *, client_id: str, job_type, runner):
        from packages.core.jobs.models import JobRecord

        job_id = f"job_{len(self._jobs)}"
        now = job_utc_now()
        record = JobRecord(
            job_id=job_id,
            client_id=client_id,
            job_type=job_type,
            status=JobStatus.RUNNING,
            created_at=now,
            updated_at=now,
        )
        try:
            result = runner()
            record.status = JobStatus.SUCCEEDED
            record.result = result
        except Exception as exc:
            record.status = JobStatus.FAILED
            record.error = str(exc)
            record.result = {}
        self._jobs[(client_id, job_id)] = record
        return record

    def get_job(self, client_id: str, job_id: str):
        return self._jobs.get((client_id, job_id))


@pytest.fixture
def pipeline_orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import shutil

    clients_root = tmp_path / "clients"
    shutil.copytree(ROOT / "tests" / "fixtures" / "clients", clients_root)
    uploads = clients_root / "tenant_a" / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "support.txt").write_text(
        "Support team phone is 2105551234 Monday through Friday.",
        encoding="utf-8",
    )
    _write_eval_suite(clients_root, "tenant_a")

    store = LocalPipelineStore(tenant_storage=TenantStorage.local(clients_root))
    from packages.adapters.cloudrun.jobs_dispatcher import DispatchResult, ExecutionOutcome

    dispatcher = MagicMock(spec=CloudRunJobsDispatcher)
    dispatcher.region = "europe-west1"
    dispatcher.job_name.side_effect = lambda jt: f"chatbot-{jt.value.replace('_', '-')}"
    pipeline_dispatch = DispatchResult(
        job_type=JobType.PIPELINE,
        job_name="chatbot-pipeline",
        region="europe-west1",
        client_id="tenant_a",
        execution_name="projects/demo/locations/europe-west1/jobs/chatbot-pipeline/executions/exec-1",
    )
    def _child_dispatch(**kwargs):
        job_type = kwargs["job_type"]
        slug = job_type.value.replace("_", "-")
        return DispatchResult(
            job_type=job_type,
            job_name=f"chatbot-{slug}",
            region="europe-west1",
            client_id=kwargs.get("client_id", "tenant_a"),
            operation_name=f"projects/demo/locations/europe-west1/operations/op-{slug}",
            execution_name=(
                f"projects/demo/locations/europe-west1/jobs/chatbot-{slug}/executions/exec-child"
            ),
        )

    child_dispatch = _child_dispatch(job_type=JobType.INGEST, client_id="tenant_a", job_id="x")
    dispatcher.dispatch_pipeline_with_meta.return_value = pipeline_dispatch
    dispatcher.dispatch_with_meta.side_effect = _child_dispatch
    terminal_execution = {
        "name": child_dispatch.execution_name,
        "completionTime": "2026-06-09T12:00:00Z",
        "completionStatus": "EXECUTION_SUCCEEDED",
        "succeededCount": 1,
        "taskCount": 1,
        "logUri": "https://logs.example/ingest",
    }
    dispatcher.wait_for_execution.return_value = terminal_execution
    dispatcher.execution_outcome.return_value = ExecutionOutcome.SUCCEEDED
    dispatcher.execution_succeeded.return_value = True
    dispatcher.execution_failure_detail.return_value = "child job failed"
    dispatcher.execution_meta.return_value = {
        "execution_name": child_dispatch.execution_name,
        "outcome": "succeeded",
        "log_uri": "https://logs.example/ingest",
    }

    monkeypatch.setenv("CLOUD_RUN_JOBS_DISABLED", "false")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo")
    monkeypatch.setattr(
        "packages.core.drive_sources.service.sync_client_drive_sources",
        lambda **kwargs: {"synced": 0},
    )

    orchestrator = PipelineOrchestrator(
        pipeline_store=store,
        job_runner=_FakeJobRunner(),
        clients_root=clients_root,
        jobs_dispatcher=dispatcher,
    )
    return {"orchestrator": orchestrator, "clients_root": clients_root, "dispatcher": dispatcher}


def test_start_dispatches_pipeline_runner_not_background_thread(pipeline_orchestrator) -> None:
    orchestrator = pipeline_orchestrator["orchestrator"]
    dispatcher = pipeline_orchestrator["dispatcher"]
    orchestrator._executor.submit = MagicMock(side_effect=AssertionError("background thread used"))

    record = orchestrator.start(client_id="tenant_a", preset="sync_only")

    assert record.status == PipelineStatus.RUNNING
    assert record.runner_execution.endswith("executions/exec-1")
    dispatcher.dispatch_pipeline_with_meta.assert_called_once_with(
        client_id="tenant_a",
        pipeline_id=record.pipeline_id,
    )
    orchestrator._executor.submit.assert_not_called()


def test_execute_pipeline_ingest_eval_updates_step_results(
    pipeline_orchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = pipeline_orchestrator["orchestrator"]
    clients_root = pipeline_orchestrator["clients_root"]
    original_build = PipelineOrchestrator._build_runner

    def _patched_build(self, **kwargs):
        if kwargs.get("step") == PipelineStep.EVAL:

            def _fake_eval() -> dict:
                manifest = read_active_manifest(active_manifest_path(clients_root, "tenant_a"))
                pending = manifest.pending or "v-pending"
                _write_passing_eval_report(clients_root, "tenant_a", pending)
                return {
                    "run_id": "pipe_eval",
                    "status": "pass",
                    "deploy_eligible": True,
                    "evaluated_index_version": pending,
                }

            return _fake_eval
        return original_build(self, **kwargs)

    monkeypatch.setattr(PipelineOrchestrator, "_build_runner", _patched_build)
    monkeypatch.setenv("CLOUD_RUN_JOBS_DISABLED", "true")
    orchestrator._executor.submit = lambda fn: None

    record = orchestrator.start(client_id="tenant_a", preset="ingest_eval", eval_llm_mode="replay")
    final = orchestrator.execute_pipeline(client_id="tenant_a", pipeline_id=record.pipeline_id)

    assert final.status == PipelineStatus.SUCCEEDED
    assert len(final.step_results) == 2
    assert final.step_results[0].step == "ingest"
    assert final.step_results[1].step == "eval"
    assert final.ingest_summary.get("chunks_total", 0) > 0
    assert final.eval_summary.get("deploy_eligible") is True


def test_child_job_failure_records_pipeline_failure(pipeline_orchestrator) -> None:
    orchestrator = pipeline_orchestrator["orchestrator"]
    dispatcher = pipeline_orchestrator["dispatcher"]
    dispatcher.execution_outcome.return_value = ExecutionOutcome.FAILED
    dispatcher.execution_succeeded.return_value = False
    dispatcher.execution_failure_detail.return_value = "drive sync container exited 1; log=https://logs"

    record = orchestrator.start(client_id="tenant_a", preset="full_deploy")
    final = orchestrator.execute_pipeline(client_id="tenant_a", pipeline_id=record.pipeline_id)

    assert final.status == PipelineStatus.FAILED
    assert final.step_results
    assert final.step_results[0].step == "drive-sync"
    assert final.step_results[0].status == "failed"
    assert "drive sync" in (final.step_results[0].error or "")
    assert not any(step.step == "ingest" for step in final.step_results)


def test_eval_fail_blocks_deploy(pipeline_orchestrator, monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = pipeline_orchestrator["orchestrator"]
    original_build = PipelineOrchestrator._build_runner

    def _patched_build(self, **kwargs):
        if kwargs.get("step") == PipelineStep.EVAL:

            def _failing_eval() -> dict:
                return {
                    "run_id": "pipe_eval_fail",
                    "status": "fail",
                    "deploy_eligible": False,
                    "evaluated_index_version": "v-pending",
                }

            return _failing_eval
        return original_build(self, **kwargs)

    monkeypatch.setattr(PipelineOrchestrator, "_build_runner", _patched_build)
    monkeypatch.setenv("CLOUD_RUN_JOBS_DISABLED", "true")
    orchestrator._executor.submit = lambda fn: None

    record = orchestrator.start(
        client_id="tenant_a",
        steps=["ingest", "eval", "deploy"],
    )
    final = orchestrator.execute_pipeline(client_id="tenant_a", pipeline_id=record.pipeline_id)

    assert final.status == PipelineStatus.FAILED
    assert any(step.step == "eval" and step.status == "failed" for step in final.step_results)
    assert not any(step.step == "deploy" for step in final.step_results)


def test_stale_pipeline_detection(pipeline_orchestrator, monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = pipeline_orchestrator["orchestrator"]
    monkeypatch.setenv("PIPELINE_STALE_TIMEOUT_SECONDS", "60")

    stale_time = utc_now() - timedelta(hours=3)
    record = PipelineRunRecord(
        pipeline_id="pipe_stale",
        client_id="tenant_a",
        status=PipelineStatus.RUNNING,
        preset="ingest_eval",
        steps=["ingest"],
        current_step="ingest",
        created_at=stale_time,
        updated_at=stale_time,
    )
    orchestrator._pipeline_store.create(record)

    assert is_pipeline_stale(record) is True
    resolved = orchestrator.get_resolved("tenant_a", "pipe_stale")
    assert resolved is not None
    assert resolved.status == PipelineStatus.STALE
    assert "stale" in (resolved.error or "").lower()


def test_mark_failed_admin_reset(pipeline_orchestrator) -> None:
    orchestrator = pipeline_orchestrator["orchestrator"]
    record = orchestrator.start(client_id="tenant_a", preset="sync_only")
    updated = orchestrator.mark_failed(
        "tenant_a",
        record.pipeline_id,
        reason="Reset stuck production run.",
    )
    assert updated.status == PipelineStatus.FAILED
    assert updated.error == "Reset stuck production run."


def test_execution_failure_detail_includes_message() -> None:
    dispatcher = CloudRunJobsDispatcher(project="demo", region="europe-west1")
    detail = dispatcher.execution_failure_detail(
        {
            "conditions": [
                {"type": "Completed", "state": "CONDITION_FAILED", "message": "container failed"},
            ],
            "logUri": "https://console.cloud.google.com/logs/viewer",
        }
    )
    assert "container failed" in detail
    assert "log=" in detail
