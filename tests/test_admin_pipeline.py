from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from apps.api.dependencies import stack as stack_module
from packages.core.ingestion.manifest import read_active_manifest
from packages.core.ingestion.paths import active_manifest_path
from packages.core.pipeline.models import PipelineStep
from packages.core.pipeline.orchestrator import PipelineOrchestrator
from packages.core.ingestion.models import IngestResult
from packages.core.pipeline.models import PIPELINE_PRESETS, resolve_pipeline_steps
from tests.test_admin_lifecycle_api import (
    ADMIN_HEADERS,
    _write_eval_suite,
    _write_passing_eval_report,
)

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"


@pytest.fixture
def pipeline_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mock_orchestrator):
    import shutil

    from apps.api.main import app

    clients_root = tmp_path / "clients"
    shutil.copytree(ROOT / "tests" / "fixtures" / "clients", clients_root)
    registry_path = tmp_path / "registry.yaml"
    shutil.copy(ROOT / "tests" / "fixtures" / "registry.yaml", registry_path)
    monkeypatch.setenv("CLIENTS_ROOT", str(clients_root))
    monkeypatch.setenv("CLIENT_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("ADMIN_JOBS_SYNC", "true")
    monkeypatch.setenv("TRACES_SQLITE_PATH", str(tmp_path / "traces.sqlite3"))
    stack_module.reset_stack()
    yield {
        "clients_root": clients_root,
        "client": TestClient(app),
    }
    stack_module.reset_stack()


def test_resolve_pipeline_presets() -> None:
    assert resolve_pipeline_steps(preset="sync_only", steps=None) == PIPELINE_PRESETS["sync_only"]
    assert resolve_pipeline_steps(preset=None, steps=["ingest", "eval"]) == resolve_pipeline_steps(
        preset="ingest_eval",
        steps=None,
    )


def test_pipeline_requires_admin_auth(pipeline_env) -> None:
    client = pipeline_env["client"]
    res = client.post(
        "/v1/admin/clients/tenant_a/pipeline/run",
        json={"preset": "ingest_eval"},
    )
    assert res.status_code == 401


def _prepare_tenant_uploads(clients_root: Path, client_id: str = "tenant_a") -> None:
    uploads = clients_root / client_id / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "support.txt").write_text(
        "Support team phone is 2105551234 Monday through Friday.",
        encoding="utf-8",
    )
    _write_eval_suite(clients_root, client_id)


def test_pipeline_happy_path_ingest_eval_deploy(
    pipeline_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients_root = pipeline_env["clients_root"]
    client = pipeline_env["client"]
    _prepare_tenant_uploads(clients_root, "tenant_a")

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
    monkeypatch.setattr(
        "packages.core.drive_sources.service.sync_client_drive_sources",
        lambda **kwargs: {"synced": 0},
    )

    res = client.post(
        "/v1/admin/clients/tenant_a/pipeline/run",
        json={"steps": ["drive-sync", "ingest", "eval", "deploy"], "eval_llm_mode": "replay"},
        headers=ADMIN_HEADERS,
    )
    assert res.status_code == 202
    pipeline_id = res.json()["pipeline_id"]

    status = client.get(
        f"/v1/admin/clients/tenant_a/pipeline/status/{pipeline_id}",
        headers=ADMIN_HEADERS,
    )
    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "succeeded"
    assert body["pending_version_after_ingest"]
    assert body["active_version_after_deploy"]
    assert body["ingest_summary"].get("chunks_total", 0) > 0
    assert body["eval_summary"].get("deploy_eligible") is True

    manifest = read_active_manifest(active_manifest_path(clients_root, "tenant_a"))
    assert manifest.active == body["active_version_after_deploy"]
    assert manifest.pending is None


def test_pipeline_eval_fail_blocks_deploy(
    pipeline_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients_root = pipeline_env["clients_root"]
    client = pipeline_env["client"]
    _prepare_tenant_uploads(clients_root, "tenant_a")

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

    res = client.post(
        "/v1/admin/clients/tenant_a/pipeline/run",
        json={"steps": ["ingest", "eval", "deploy"]},
        headers=ADMIN_HEADERS,
    )
    body = client.get(
        f"/v1/admin/clients/tenant_a/pipeline/status/{res.json()['pipeline_id']}",
        headers=ADMIN_HEADERS,
    ).json()
    assert body["status"] == "failed"
    assert any(step["step"] == "eval" and step["status"] == "failed" for step in body["step_results"])
    assert not any(step["step"] == "deploy" for step in body["step_results"])


def test_pipeline_empty_ingest_blocks_deploy(pipeline_env, monkeypatch: pytest.MonkeyPatch) -> None:
    client = pipeline_env["client"]

    monkeypatch.setattr(
        "packages.core.ingestion.pipeline.ingest_client_uploads",
        lambda **kwargs: IngestResult(
            client_id="tenant_a",
            version_id="v-empty",
            chunk_count=0,
            source_count=0,
            indexed_count=0,
            skipped_count=0,
            skipped_unchanged_count=0,
            unsupported_count=0,
            failed_count=0,
            embed_enabled=False,
        ),
    )

    res = client.post(
        "/v1/admin/clients/tenant_a/pipeline/run",
        json={"steps": ["ingest", "deploy"]},
        headers=ADMIN_HEADERS,
    )
    body = client.get(
        f"/v1/admin/clients/tenant_a/pipeline/status/{res.json()['pipeline_id']}",
        headers=ADMIN_HEADERS,
    ).json()
    assert body["status"] == "failed"
    assert any(step["step"] == "ingest" and step["status"] == "failed" for step in body["step_results"])
    assert not any(step["step"] == "deploy" for step in body["step_results"])


def test_pipeline_failure_stops_later_steps(pipeline_env, monkeypatch: pytest.MonkeyPatch) -> None:
    client = pipeline_env["client"]

    def _boom(**kwargs):
        raise RuntimeError("drive sync failed")

    monkeypatch.setattr("packages.core.drive_sources.service.sync_client_drive_sources", _boom)

    res = client.post(
        "/v1/admin/clients/tenant_a/pipeline/run",
        json={"preset": "full_deploy"},
        headers=ADMIN_HEADERS,
    )
    body = client.get(
        f"/v1/admin/clients/tenant_a/pipeline/status/{res.json()['pipeline_id']}",
        headers=ADMIN_HEADERS,
    ).json()
    assert body["status"] == "failed"
    assert body["step_results"][0]["step"] == "drive-sync"
    assert not any(step["step"] == "ingest" for step in body["step_results"])


def test_pipeline_start_returns_pending_without_sync_mode(
    pipeline_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ADMIN_JOBS_SYNC", raising=False)
    client = pipeline_env["client"]
    res = client.post(
        "/v1/admin/clients/tenant_a/pipeline/run",
        json={"preset": "sync_only"},
        headers=ADMIN_HEADERS,
    )
    assert res.status_code == 202
    body = res.json()
    assert body["status"] == "pending"
    assert body["pipeline_id"].startswith("pipe_")


def test_pipeline_list_runs(pipeline_env) -> None:
    client = pipeline_env["client"]
    res = client.get("/v1/admin/clients/tenant_a/pipeline/runs", headers=ADMIN_HEADERS)
    assert res.status_code == 200
    assert isinstance(res.json(), list)
