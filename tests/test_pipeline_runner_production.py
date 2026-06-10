from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from packages.adapters.cloudrun.jobs_dispatcher import (
    CloudRunJobsDispatcher,
    DispatchResult,
    ExecutionOutcome,
)
from packages.adapters.pipeline.local_pipeline_store import LocalPipelineStore
from packages.core.ingestion.manifest import read_active_manifest, write_active_manifest
from packages.core.ingestion.models import ActiveManifest
from packages.core.ingestion.paths import active_manifest_path, ingest_report_path
from packages.core.jobs.models import JobType
from packages.core.pipeline.models import PipelineStatus, PipelineStep
from packages.core.pipeline.orchestrator import PipelineOrchestrator
from packages.core.storage.tenant_storage import TenantStorage
from tests.test_admin_lifecycle_api import _write_eval_suite, _write_passing_eval_report

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def production_like_orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
    dispatcher = MagicMock(spec=CloudRunJobsDispatcher)
    dispatcher.region = "europe-west1"
    dispatcher.job_name.side_effect = lambda jt: f"chatbot-{jt.value.replace('_', '-')}"

    operation_name = "projects/demo/locations/europe-west1/operations/op-ingest"
    execution_name = (
        "projects/demo/locations/europe-west1/jobs/chatbot-ingest/executions/chatbot-ingest-mdsnd"
    )
    ingest_dispatch = DispatchResult(
        job_type=JobType.INGEST,
        job_name="chatbot-ingest",
        region="europe-west1",
        client_id="tenant_a",
        operation_name=operation_name,
        execution_name=execution_name,
    )
    eval_dispatch = DispatchResult(
        job_type=JobType.EVAL,
        job_name="chatbot-eval",
        region="europe-west1",
        client_id="tenant_a",
        operation_name="projects/demo/locations/europe-west1/operations/op-eval",
        execution_name="projects/demo/locations/europe-west1/jobs/chatbot-eval/executions/chatbot-eval-1",
    )

    def _dispatch_side_effect(**kwargs):
        if kwargs["job_type"] == JobType.INGEST:
            return ingest_dispatch
        if kwargs["job_type"] == JobType.EVAL:
            return eval_dispatch
        raise AssertionError(f"unexpected dispatch {kwargs['job_type']}")

    dispatcher.dispatch_with_meta.side_effect = _dispatch_side_effect

    ingest_terminal = {
        "name": execution_name,
        "completionTime": "2026-06-09T12:00:00Z",
        "completionStatus": "EXECUTION_SUCCEEDED",
        "succeededCount": 1,
        "taskCount": 1,
        "logUri": "https://logs.example/ingest",
    }
    eval_terminal = {
        "name": eval_dispatch.execution_name,
        "completionTime": "2026-06-09T12:10:00Z",
        "completionStatus": "EXECUTION_SUCCEEDED",
        "succeededCount": 1,
        "taskCount": 1,
    }

    def _wait_side_effect(execution_name, **kwargs):
        if execution_name == ingest_dispatch.execution_name:
            return ingest_terminal
        if execution_name == eval_dispatch.execution_name:
            return eval_terminal
        raise AssertionError(f"unexpected wait {execution_name}")

    dispatcher.wait_for_execution.side_effect = _wait_side_effect
    dispatcher.execution_outcome.side_effect = lambda ex: ExecutionOutcome.SUCCEEDED
    dispatcher.execution_succeeded.return_value = True
    dispatcher.execution_meta.side_effect = lambda ex: {
        "execution_name": ex.get("name"),
        "outcome": "succeeded",
        "log_uri": ex.get("logUri"),
    }

    monkeypatch.setenv("CLOUD_RUN_JOBS_DISABLED", "false")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo")
    monkeypatch.setenv("ADMIN_JOBS_SYNC", "true")

    class _FakeJobRunner:
        def submit(self, **kwargs):
            raise AssertionError("in-process runner should not be used")

        def get_job(self, client_id, job_id):
            return None

    orchestrator = PipelineOrchestrator(
        pipeline_store=store,
        job_runner=_FakeJobRunner(),
        clients_root=clients_root,
        jobs_dispatcher=dispatcher,
    )
    return {
        "orchestrator": orchestrator,
        "clients_root": clients_root,
        "dispatcher": dispatcher,
        "ingest_dispatch": ingest_dispatch,
        "ingest_terminal": ingest_terminal,
    }


def test_ingest_success_writes_step_results_and_advances_to_eval(
    production_like_orchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = production_like_orchestrator["orchestrator"]
    clients_root = production_like_orchestrator["clients_root"]
    ingest_dispatch = production_like_orchestrator["ingest_dispatch"]

    original_ingest = PipelineOrchestrator._run_step_via_cloud_run

    def _ingest_then_eval(self, **kwargs):
        if kwargs.get("step") == PipelineStep.INGEST:
            pending_version = "2026-06-09T120000_0001"
            manifest = read_active_manifest(active_manifest_path(clients_root, "tenant_a"))
            manifest.pending = pending_version
            write_active_manifest(active_manifest_path(clients_root, "tenant_a"), manifest)
            report_path = ingest_report_path(clients_root, "tenant_a", pending_version)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(
                    {
                        "sources_total": 34,
                        "indexed": 34,
                        "chunks_total": 2797,
                    }
                ),
                encoding="utf-8",
            )
            _write_passing_eval_report(clients_root, "tenant_a", pending_version)
            return PipelineOrchestrator._step_result_from_execution(
                self,
                step=PipelineStep.INGEST,
                job_id="job_ingest",
                dispatch=ingest_dispatch,
                execution=production_like_orchestrator["ingest_terminal"],
                status="succeeded",
                result={
                    "version_id": pending_version,
                    "source_count": 34,
                    "indexed_count": 34,
                    "chunk_count": 2797,
                },
            )
        return original_ingest(self, **kwargs)

    monkeypatch.setattr(PipelineOrchestrator, "_run_step_via_cloud_run", _ingest_then_eval)

    record = orchestrator.start(client_id="tenant_a", preset="ingest_eval", eval_llm_mode="replay")
    assert record.status == PipelineStatus.SUCCEEDED
    assert len(record.step_results) == 2
    ingest_step = record.step_results[0]
    assert ingest_step.step == "ingest"
    assert ingest_step.status == "succeeded"
    assert ingest_step.cloud_run_execution == ingest_dispatch.execution_name
    assert ingest_step.execution_meta.get("operation_name") == ingest_dispatch.operation_name
    assert record.pending_version_after_ingest
    assert record.ingest_summary.get("chunks_total", 0) > 0
    assert record.eval_summary.get("status") == "pass"
    assert record.eval_summary.get("deploy_eligible") is True


def test_runner_stdout_logs(capsys) -> None:
    from packages.core.pipeline.logging_util import pipeline_log

    pipeline_log("hello production")
    captured = capsys.readouterr()
    assert "[pipeline] hello production" in captured.out
