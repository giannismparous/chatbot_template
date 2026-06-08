from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from packages.adapters.storage.gcs_file_store import GcsFileStore
from packages.core.config.loader import TenantConfigLoader
from packages.core.eval.gate import check_deploy_gate
from packages.core.eval.paths import latest_eval_report_path
from packages.core.stack.factory import project_root
from packages.core.storage.eval_output_sync import (
    hydrate_client_eval_report,
    persist_eval_output_to_storage,
)
from packages.core.storage.keys import gcs_object_name
from packages.core.storage.tenant_cache_hydrator import ensure_firebase_eval_assets_hydrated

MINIMAL_CLIENT_YAML = b"""client_id: default
display_name: Default
domain_pack: generic
default_mode: hybrid_local
modes:
  - hybrid_local
source_weights: {}
"""

MINIMAL_EVAL_SUITE = b"""version: 1
client_id: default
target:
  index_scope: pending
  mode: hybrid_local
thresholds:
  retrieval_min_pass_rate: 0.9
  answer_min_pass_rate: 0.85
  safety_min_pass_rate: 1.0
  citation_min_pass_rate: 1.0
required_categories:
  - answer
freshness_hours: 24
regulated:
  require_citation_tests: false
export:
  reviewer:
    formats: [csv]
    bundle_visibility: public_only
"""

MINIMAL_EVAL_CASE = b"""cases:
  - id: smoke_answer
    category: answer
    message: hello
    expect:
      expected_contains: [hello]
"""

PENDING_VERSION = "2026-06-07T232651_0000"


def _make_gcs_store(cache_root: Path, objects: dict[str, bytes]) -> GcsFileStore:
    bucket = MagicMock()

    def _blob(name: str) -> MagicMock:
        blob = MagicMock()
        blob.name = name
        blob.exists.side_effect = lambda: name in objects

        def download_to_filename(path: str) -> None:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(objects[name])

        def upload_from_string(data, content_type=None) -> None:
            payload = data if isinstance(data, bytes) else str(data).encode("utf-8")
            objects[name] = payload

        blob.download_to_filename.side_effect = download_to_filename
        blob.upload_from_string.side_effect = upload_from_string
        return blob

    bucket.blob.side_effect = _blob

    def list_blobs(prefix: str = "") -> list[MagicMock]:
        return [_blob(name) for name in sorted(objects) if name.startswith(prefix)]

    bucket.list_blobs.side_effect = list_blobs
    client = MagicMock()
    client.bucket.return_value = bucket
    return GcsFileStore(
        bucket_name="simasia-chatbot-prod-demo",
        cache_root=cache_root,
        client=client,
    )


def _latest_report_payload(*, run_id: str) -> dict:
    return {
        "run_id": run_id,
        "client_id": "default",
        "status": "pass",
        "evaluated_index_version": PENDING_VERSION,
        "evaluated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "categories": {
            "answer": {
                "total": 1,
                "passed": 1,
                "pass_rate": 1.0,
                "threshold": 0.85,
                "status": "pass",
            }
        },
        "regulated": {
            "regulated_mode": False,
            "citation_tests_required": False,
            "citation_tests_present": False,
            "citation_tests_passed": False,
        },
        "deploy_eligible": True,
        "report_path": f"/tmp/default/tests/output/{run_id}/eval_report.json",
        "failure_reasons": [],
        "failed_cases": [],
    }


def test_persist_eval_output_uploads_latest_and_run_dir(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    clients_root = cache
    run_id = "eval_20260608T022406Z"
    run_dir = clients_root / "default" / "tests" / "output" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "eval_report.json").write_text('{"status":"pass"}\n', encoding="utf-8")
    (run_dir / "eval_run.json").write_text('{"cases":[]}\n', encoding="utf-8")
    latest_path = clients_root / "default" / "tests" / "output" / "latest_eval_report.json"
    latest_path.write_text(
        json.dumps(_latest_report_payload(run_id=run_id), indent=2) + "\n",
        encoding="utf-8",
    )

    objects: dict[str, bytes] = {}
    store = _make_gcs_store(cache, objects)
    count = persist_eval_output_to_storage(
        client_id="default",
        file_store=store,
        clients_root=clients_root,
        run_dir=run_dir,
        latest_path=latest_path,
    )
    assert count >= 3
    assert gcs_object_name("default", "tests/output/latest_eval_report.json") in objects
    assert gcs_object_name("default", f"tests/output/{run_id}/eval_report.json") in objects
    assert gcs_object_name("default", f"tests/output/{run_id}/eval_run.json") in objects


def test_deploy_gate_passes_after_hydrating_latest_eval_report_from_gcs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.core.stack import factory

    cache = tmp_path / "cache"
    run_id = "eval_20260608T022406Z"
    latest_payload = _latest_report_payload(run_id=run_id)
    manifest = {
        "active": None,
        "pending": PENDING_VERSION,
        "previous": None,
    }
    knowledge_index = {
        "client_id": "default",
        "version_id": PENDING_VERSION,
        "chunks": [{"id": "c1", "content": "hello", "title": "t"}],
    }
    objects = {
        gcs_object_name("default", "config/client.yaml"): MINIMAL_CLIENT_YAML,
        gcs_object_name("default", "tests/eval_suite.yaml"): MINIMAL_EVAL_SUITE,
        gcs_object_name("default", "tests/cases/smoke.yaml"): MINIMAL_EVAL_CASE,
        gcs_object_name("default", "indexes/active_manifest.json"): json.dumps(manifest).encode() + b"\n",
        gcs_object_name(
            "default",
            f"indexes/versions/{PENDING_VERSION}/knowledge_index.json",
        ): json.dumps(knowledge_index).encode() + b"\n",
        gcs_object_name("default", "tests/output/latest_eval_report.json"): (
            json.dumps(latest_payload, indent=2) + "\n"
        ).encode(),
        gcs_object_name("default", f"tests/output/{run_id}/eval_report.json"): (
            json.dumps(latest_payload, indent=2) + "\n"
        ).encode(),
    }
    gcs_store = _make_gcs_store(cache, objects)

    monkeypatch.setenv("STACK_PROFILE", "firebase")
    monkeypatch.setenv("FIRESTORE_CONTROL_PLANE", "false")
    monkeypatch.setenv("GCS_REGISTRY_FALLBACK", "true")
    monkeypatch.setenv("ADMIN_API_TOKEN", "secret")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo")
    monkeypatch.setenv("GCS_BUCKET", "simasia-chatbot-prod-demo")
    monkeypatch.setenv("TENANT_CACHE_ROOT", str(cache))
    monkeypatch.setenv(
        "CLIENT_REGISTRY_PATH",
        str(project_root() / "tests" / "fixtures" / "registry.yaml"),
    )
    monkeypatch.setattr(factory, "build_file_store", lambda profile, stack_yaml, root: gcs_store)

    assert not latest_eval_report_path(cache, "default").is_file()
    ensure_firebase_eval_assets_hydrated(client_id="default")
    assert latest_eval_report_path(cache, "default").is_file()

    loader = TenantConfigLoader(
        clients_root=cache,
        domain_packs_root=project_root() / "packages" / "domain_packs",
    )
    gate = check_deploy_gate(clients_root=cache, client_id="default", config_loader=loader)
    assert gate.allowed is True
    assert gate.reason == "ok"
    assert gate.report is not None
    assert gate.report.deploy_eligible is True


def test_hydrate_client_eval_report_skips_unrelated_output_blobs(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    run_id = "eval_20260608T022406Z"
    stale_run = "eval_20260101T000000Z"
    objects = {
        gcs_object_name("default", "tests/output/latest_eval_report.json"): (
            json.dumps(_latest_report_payload(run_id=run_id), indent=2) + "\n"
        ).encode(),
        gcs_object_name("default", f"tests/output/{run_id}/eval_report.json"): b'{"status":"pass"}\n',
        gcs_object_name("default", f"tests/output/{stale_run}/eval_report.json"): b'{"status":"fail"}\n',
    }
    store = _make_gcs_store(cache, objects)
    hydrated = hydrate_client_eval_report(client_id="default", file_store=store)
    assert hydrated == 2
    assert latest_eval_report_path(cache, "default").is_file()
    assert (cache / "default" / "tests" / "output" / run_id / "eval_report.json").is_file()
    assert not (cache / "default" / "tests" / "output" / stale_run / "eval_report.json").exists()
