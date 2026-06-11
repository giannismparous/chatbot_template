from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from packages.adapters.cloudrun.jobs_dispatcher import DispatchResult
from packages.core.jobs.models import JobType
from packages.core.pipeline.models import PipelineStatus
from packages.core.pipeline.orchestrator import PipelineOrchestrator


def test_api_pipeline_dispatch_returns_without_blocking_poll(tmp_path, monkeypatch):
    from packages.adapters.pipeline.local_pipeline_store import LocalPipelineStore
    from packages.core.storage.tenant_storage import TenantStorage
    import shutil
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    clients_root = tmp_path / "clients"
    shutil.copytree(root / "tests" / "fixtures" / "clients", clients_root)
    store = LocalPipelineStore(tenant_storage=TenantStorage.local(clients_root))

    dispatcher = MagicMock()
    monkeypatch.setenv("CLOUD_RUN_JOBS_DISABLED", "false")
    monkeypatch.delenv("ADMIN_JOBS_SYNC", raising=False)

    orch = PipelineOrchestrator(
        pipeline_store=store,
        job_runner=MagicMock(),
        clients_root=clients_root,
        jobs_dispatcher=dispatcher,
    )

    dispatch_result = DispatchResult(
        job_type=JobType.PIPELINE,
        job_name="chatbot-pipeline",
        region="europe-west1",
        client_id="tenant_a",
        operation_name="projects/demo/locations/europe-west1/operations/op-fast",
        execution_name="projects/demo/locations/europe-west1/operations/op-fast",
    )

    def _slow_dispatch(**kwargs):
        time.sleep(0.05)
        return dispatch_result

    dispatcher.dispatch_pipeline_with_meta.side_effect = _slow_dispatch

    start = time.time()
    record = orch.start(client_id="tenant_a", preset="sync_only")
    elapsed = time.time() - start

    assert elapsed < 2.0
    assert record.status == PipelineStatus.RUNNING
    dispatcher.dispatch_pipeline_with_meta.assert_called_once()
    call_kwargs = dispatcher.dispatch_pipeline_with_meta.call_args.kwargs
    assert call_kwargs.get("blocking_resolve") is False


def test_api_dispatch_failure_marks_pipeline_failed(tmp_path, monkeypatch):
    from packages.adapters.pipeline.local_pipeline_store import LocalPipelineStore
    from packages.core.storage.tenant_storage import TenantStorage
    import shutil
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    clients_root = tmp_path / "clients"
    shutil.copytree(root / "tests" / "fixtures" / "clients", clients_root)
    store = LocalPipelineStore(tenant_storage=TenantStorage.local(clients_root))

    dispatcher = MagicMock()
    dispatcher.dispatch_pipeline_with_meta.side_effect = RuntimeError("dispatch timeout")

    monkeypatch.setenv("CLOUD_RUN_JOBS_DISABLED", "false")
    monkeypatch.delenv("ADMIN_JOBS_SYNC", raising=False)

    orch = PipelineOrchestrator(
        pipeline_store=store,
        job_runner=MagicMock(),
        clients_root=clients_root,
        jobs_dispatcher=dispatcher,
    )

    with pytest.raises(RuntimeError, match="dispatch timeout"):
        orch.start(client_id="tenant_a", preset="sync_only")

    runs = store.list_runs("tenant_a", limit=1)
    assert runs
    assert runs[0].status == PipelineStatus.FAILED
    assert "dispatch" in (runs[0].error or "").lower()
