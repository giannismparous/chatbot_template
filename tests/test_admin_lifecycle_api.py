from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.dependencies import stack as stack_module
from packages.config.loaders import load_yaml, save_yaml
from packages.core.eval.paths import latest_eval_report_path
from packages.core.ingestion.manifest import read_active_manifest
from packages.core.ingestion.paths import active_manifest_path, knowledge_index_path
from packages.core.ingestion.pipeline import ingest_client_uploads

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
PACKS = ROOT / "packages" / "domain_packs"
ADMIN_HEADERS = {"x-admin-token": "test-admin-token"}


@pytest.fixture
def lifecycle_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mock_orchestrator):
    clients_root = tmp_path / "clients"
    shutil.copytree(FIXTURES / "clients", clients_root)
    registry_path = tmp_path / "registry.yaml"
    shutil.copy(FIXTURES / "registry.yaml", registry_path)
    monkeypatch.setenv("CLIENTS_ROOT", str(clients_root))
    monkeypatch.setenv("CLIENT_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("ADMIN_JOBS_SYNC", "true")
    monkeypatch.setenv("TRACES_SQLITE_PATH", str(tmp_path / "traces.sqlite3"))
    stack_module.reset_stack()
    from apps.api.main import app

    yield {
        "clients_root": clients_root,
        "registry_path": registry_path,
        "client": TestClient(app),
    }
    stack_module.reset_stack()


def _write_eval_suite(clients_root: Path, client_id: str) -> None:
    tests = clients_root / client_id / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    save_yaml(
        str(tests / "eval_suite.yaml"),
        {
            "version": 1,
            "client_id": client_id,
            "target": {"index_scope": "pending", "mode": "hybrid_local"},
            "thresholds": {
                "retrieval_min_pass_rate": 0.9,
                "answer_min_pass_rate": 0.85,
                "safety_min_pass_rate": 1.0,
                "citation_min_pass_rate": 1.0,
            },
            "required_categories": ["retrieval"],
            "freshness_hours": 24,
            "regulated": {"require_citation_tests": False},
        },
    )
    cases_dir = tests / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    save_yaml(
        str(cases_dir / "suite.yaml"),
        {
            "cases": [
                {
                    "id": "ret1",
                    "category": "retrieval",
                    "message": "support phone",
                    "expect": {"expected_no_context": False, "expected_top_k_contains": ["2105551234"]},
                }
            ]
        },
    )


def _write_passing_eval_report(clients_root: Path, client_id: str, version_id: str) -> None:
    out = clients_root / client_id / "tests" / "output"
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": "run_test",
        "client_id": client_id,
        "status": "pass",
        "evaluated_index_version": version_id,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "deploy_eligible": True,
        "categories": {"retrieval": {"total": 1, "passed": 1, "pass_rate": 1.0, "status": "pass"}},
        "regulated": {"regulated_mode": False},
    }
    (out / "latest_eval_report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _setup_tenant_for_jobs(clients_root: Path, client_id: str = "tenant_a") -> str:
    from packages.core.config.loader import TenantConfigLoader

    uploads = clients_root / client_id / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "support.txt").write_text(
        "Support team phone is 2105551234 Monday through Friday.",
        encoding="utf-8",
    )
    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    result = ingest_client_uploads(
        clients_root=clients_root,
        client_id=client_id,
        config_loader=loader,
        version_id="v-pending",
    )
    path = knowledge_index_path(clients_root, client_id, result.version_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    for chunk in payload.get("chunks") or []:
        chunk["citation_url"] = "https://example.com/privacy"
        chunk["source_visibility"] = "public"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_eval_suite(clients_root, client_id)
    return result.version_id


def test_admin_routes_401_without_token(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    assert client.get("/v1/admin/clients").status_code == 401
    assert client.post("/v1/admin/clients", json={"client_id": "x"}).status_code == 401


def test_widget_key_rejected_on_admin_routes(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    res = client.get(
        "/v1/admin/clients",
        headers={"x-client-key": "wk_test_tenant_a", "Origin": "http://testserver"},
    )
    assert res.status_code == 401


def test_create_client_skeleton_registry_eval_templates(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    clients_root = lifecycle_env["clients_root"]
    res = client.post(
        "/v1/admin/clients",
        json={"client_id": "acme_new", "display_name": "Acme New", "allowed_origins": ["http://localhost"]},
        headers=ADMIN_HEADERS,
    )
    assert res.status_code == 201
    body = res.json()
    assert body["client_id"] == "acme_new"
    assert body.get("widget_key") is None
    assert body["widget_key_prefix"].endswith("...")
    assert (clients_root / "acme_new" / "config" / "client.yaml").is_file()
    assert (clients_root / "acme_new" / "tests" / "eval_suite.yaml").is_file()
    assert (clients_root / "acme_new" / "tests" / "cases" / "starter.yaml").is_file()
    from packages.config.loaders import load_yaml

    registry = load_yaml(str(lifecycle_env["registry_path"]))
    assert "acme_new" in registry["clients"]


def test_create_client_reveal_widget_key_once(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    res = client.post(
        "/v1/admin/clients",
        json={"client_id": "reveal_co", "reveal_widget_key": True},
        headers=ADMIN_HEADERS,
    )
    assert res.status_code == 201
    body = res.json()
    assert body["widget_key"].startswith("wk_")
    get_res = client.get("/v1/admin/clients/reveal_co", headers=ADMIN_HEADERS)
    assert "widget_key" not in get_res.json()
    keys = get_res.json()["widget_keys"]
    assert keys[0]["key_prefix"]
    assert "public_key" not in keys[0]


def test_list_get_client_no_secrets(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    listed = client.get("/v1/admin/clients", headers=ADMIN_HEADERS).json()
    tenant_a = next(x for x in listed if x["client_id"] == "tenant_a")
    assert "public_key" not in json.dumps(tenant_a)
    detail = client.get("/v1/admin/clients/tenant_a", headers=ADMIN_HEADERS).json()
    assert "public_key" not in json.dumps(detail)


def test_config_get_put_allowlisted(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    get_res = client.get("/v1/admin/clients/tenant_a/config/themes", headers=ADMIN_HEADERS)
    assert get_res.status_code == 200
    put_res = client.put(
        "/v1/admin/clients/tenant_a/config/themes",
        json={"data": {"colors": {"primary": "#112233"}, "logo_url": ""}},
        headers=ADMIN_HEADERS,
    )
    assert put_res.status_code == 200


def test_config_put_invalid_returns_422(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    res = client.put(
        "/v1/admin/clients/tenant_a/config/privacy",
        json={"data": {"mode": "not-a-valid-mode"}},
        headers=ADMIN_HEADERS,
    )
    assert res.status_code == 422


def test_config_key_traversal_rejected(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    res = client.get("/v1/admin/clients/tenant_a/config/../secrets", headers=ADMIN_HEADERS)
    assert res.status_code in {400, 404}


def test_upload_valid_file(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    clients_root = lifecycle_env["clients_root"]
    res = client.post(
        "/v1/admin/clients/tenant_a/uploads",
        headers=ADMIN_HEADERS,
        files={"file": ("notes.txt", b"hello upload", "text/plain")},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["path"] == "notes.txt"
    assert ":\\" not in body["path"]
    assert (clients_root / "tenant_a" / "uploads" / "notes.txt").is_file()


@pytest.mark.parametrize(
    "filename",
    [
        "../evil.txt",
        "/etc/passwd",
        "secrets.env",
        "credentials.json",
        "payload.exe",
        "folder\\bad.txt",
    ],
)
def test_upload_rejected_paths(lifecycle_env, filename: str) -> None:
    client = lifecycle_env["client"]
    res = client.post(
        "/v1/admin/clients/tenant_a/uploads",
        headers=ADMIN_HEADERS,
        files={"file": (filename, b"x", "application/octet-stream")},
    )
    assert res.status_code == 400


def test_delete_upload_tenant_contained(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    clients_root = lifecycle_env["clients_root"]
    target = clients_root / "tenant_a" / "uploads" / "remove_me.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")
    res = client.delete("/v1/admin/clients/tenant_a/uploads/remove_me.txt", headers=ADMIN_HEADERS)
    assert res.status_code == 204
    assert not target.is_file()


def test_ingest_job_creates_pending_version(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    clients_root = lifecycle_env["clients_root"]
    uploads = clients_root / "tenant_a" / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "doc.txt").write_text("Support phone 2105551234", encoding="utf-8")
    res = client.post("/v1/admin/clients/tenant_a/jobs/ingest", headers=ADMIN_HEADERS)
    assert res.status_code == 202
    job_id = res.json()["job_id"]
    job = client.get(f"/v1/admin/clients/tenant_a/jobs/{job_id}", headers=ADMIN_HEADERS).json()
    assert job["status"] == "succeeded"
    manifest = read_active_manifest(active_manifest_path(clients_root, "tenant_a"))
    assert manifest.pending is not None


def test_eval_job_creates_report(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    clients_root = lifecycle_env["clients_root"]
    _setup_tenant_for_jobs(clients_root, "tenant_a")
    res = client.post(
        "/v1/admin/clients/tenant_a/jobs/eval",
        json={"suite": "retrieval", "llm_mode": "replay"},
        headers=ADMIN_HEADERS,
    )
    assert res.status_code == 202
    job_id = res.json()["job_id"]
    job = client.get(f"/v1/admin/clients/tenant_a/jobs/{job_id}", headers=ADMIN_HEADERS).json()
    assert job["status"] == "succeeded"
    assert latest_eval_report_path(clients_root, "tenant_a").is_file()


def test_deploy_success_activates_pending(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    clients_root = lifecycle_env["clients_root"]
    version = _setup_tenant_for_jobs(clients_root, "tenant_a")
    _write_passing_eval_report(clients_root, "tenant_a", version)
    res = client.post("/v1/admin/clients/tenant_a/deploy", json={}, headers=ADMIN_HEADERS)
    assert res.status_code == 200
    assert res.json()["activated_version"] == version
    manifest = read_active_manifest(active_manifest_path(clients_root, "tenant_a"))
    assert manifest.active == version
    assert manifest.pending is None


@pytest.mark.parametrize(
    "mutator,expected_reason",
    [
        (lambda cr, cid, v: None, "no_eval_report"),
        (
            lambda cr, cid, v: _write_passing_eval_report(cr, cid, "wrong-version"),
            "eval_version_mismatch",
        ),
        (
            lambda cr, cid, v: _write_stale_eval_report(cr, cid, v),
            "eval_expired",
        ),
        (
            lambda cr, cid, v: _write_failing_eval_report(cr, cid, v),
            "eval_failed",
        ),
    ],
)
def test_deploy_gate_failures_return_409(lifecycle_env, mutator, expected_reason) -> None:
    client = lifecycle_env["client"]
    clients_root = lifecycle_env["clients_root"]
    version = _setup_tenant_for_jobs(clients_root, "tenant_a")
    if mutator:
        mutator(clients_root, "tenant_a", version)
    elif expected_reason == "no_eval_report":
        latest = latest_eval_report_path(clients_root, "tenant_a")
        if latest.is_file():
            latest.unlink()
    res = client.post("/v1/admin/clients/tenant_a/deploy", json={}, headers=ADMIN_HEADERS)
    assert res.status_code == 409
    detail = res.json()["detail"]
    if isinstance(detail, dict):
        assert detail["reason"] == expected_reason
    else:
        assert expected_reason in str(detail)


def _write_stale_eval_report(clients_root: Path, client_id: str, version_id: str) -> None:
    stale = datetime.now(timezone.utc) - timedelta(hours=48)
    out = clients_root / client_id / "tests" / "output"
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": "run_stale",
        "client_id": client_id,
        "status": "pass",
        "evaluated_index_version": version_id,
        "evaluated_at": stale.isoformat(),
        "deploy_eligible": True,
        "categories": {"retrieval": {"total": 1, "passed": 1, "pass_rate": 1.0, "status": "pass"}},
    }
    (out / "latest_eval_report.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_failing_eval_report(clients_root: Path, client_id: str, version_id: str) -> None:
    out = clients_root / client_id / "tests" / "output"
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": "run_fail",
        "client_id": client_id,
        "status": "fail",
        "evaluated_index_version": version_id,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "deploy_eligible": False,
        "categories": {"retrieval": {"total": 1, "passed": 0, "pass_rate": 0.0, "status": "fail"}},
    }
    (out / "latest_eval_report.json").write_text(json.dumps(payload), encoding="utf-8")


def test_deploy_endpoint_has_no_skip_gate_bypass(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    res = client.post(
        "/v1/admin/clients/tenant_a/deploy",
        json={"skip_gate": True},
        headers=ADMIN_HEADERS,
    )
    assert res.status_code in {409, 422}


def test_rollback_endpoint(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    clients_root = lifecycle_env["clients_root"]
    from packages.core.config.loader import TenantConfigLoader

    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    v1 = _setup_tenant_for_jobs(clients_root, "tenant_a")
    _write_passing_eval_report(clients_root, "tenant_a", v1)
    client.post("/v1/admin/clients/tenant_a/deploy", json={}, headers=ADMIN_HEADERS)

    uploads = clients_root / "tenant_a" / "uploads"
    (uploads / "doc2.txt").write_text("Another doc 2105559999", encoding="utf-8")
    result = ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=loader,
        version_id="v-second",
    )
    _write_passing_eval_report(clients_root, "tenant_a", result.version_id)
    client.post("/v1/admin/clients/tenant_a/deploy", json={}, headers=ADMIN_HEADERS)

    res = client.post("/v1/admin/clients/tenant_a/rollback", headers=ADMIN_HEADERS)
    assert res.status_code == 200
    assert res.json()["active_version"] == v1


def test_upload_null_byte_rejected_by_validator() -> None:
    from packages.core.admin.upload_safety import UploadValidationError, validate_upload_relative_path

    with pytest.raises(UploadValidationError):
        validate_upload_relative_path("bad\x00name.txt")


def test_metrics_aggregate_safe_only(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    from apps.api.dependencies.stack import get_stack

    stack = get_stack()
    storable = {
        "client_id": "tenant_a",
        "confidence": 0.8,
        "no_context": False,
        "crisis": False,
        "input_blocked": False,
        "provider_fallback": False,
        "latency_ms": 120,
        "message": "user secret message",
        "answer": "bot answer with PII",
    }
    stack.metrics_store.record_chat("tenant_a", storable)
    res = client.get("/v1/admin/clients/tenant_a/metrics", headers=ADMIN_HEADERS)
    assert res.status_code == 200
    body = res.json()
    dumped = json.dumps(body)
    assert "secret message" not in dumped
    assert "bot answer" not in dumped
    assert body["total_chats"] >= 1
    assert "confidence_buckets" in body


def test_upload_list_includes_citation_status_internal(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    clients_root = lifecycle_env["clients_root"]
    target = clients_root / "tenant_a" / "uploads" / "mapped.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("content", encoding="utf-8")
    res = client.get("/v1/admin/clients/tenant_a/uploads", headers=ADMIN_HEADERS)
    assert res.status_code == 200
    entry = next(item for item in res.json()["files"] if item["path"] == "mapped.txt")
    assert entry["citation"]["status"] == "internal_only"
    assert ":\\" not in json.dumps(entry)


def test_put_upload_citation_and_delete(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    clients_root = lifecycle_env["clients_root"]
    config_dir = clients_root / "tenant_a" / "config"
    save_yaml(
        str(config_dir / "source_whitelist.yaml"),
        {"allowed_public_domains": ["example.com"], "citation_url_rules": {"allow_only_whitelisted": True}},
    )
    target = clients_root / "tenant_a" / "uploads" / "policy.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("policy text", encoding="utf-8")

    put = client.put(
        "/v1/admin/clients/tenant_a/uploads/policy.txt/citation",
        headers=ADMIN_HEADERS,
        json={
            "citation_url": "https://example.com/policy",
            "title": "Policy",
            "source_visibility": "public",
        },
    )
    assert put.status_code == 200
    assert put.json()["status"] == "public_configured"
    assert put.json()["requires_reingest"] is True

    blocked = client.put(
        "/v1/admin/clients/tenant_a/uploads/policy.txt/citation",
        headers=ADMIN_HEADERS,
        json={
            "citation_url": "https://other.com/policy",
            "source_visibility": "public",
        },
    )
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked_by_whitelist"

    delete = client.delete("/v1/admin/clients/tenant_a/uploads/policy.txt/citation", headers=ADMIN_HEADERS)
    assert delete.status_code == 204


def test_citation_endpoints_reject_traversal(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    res = client.put(
        "/v1/admin/clients/tenant_a/uploads/../secrets.txt/citation",
        headers=ADMIN_HEADERS,
        json={"citation_url": "https://example.com/x", "source_visibility": "public"},
    )
    assert res.status_code in {400, 404, 422}


def test_widget_key_cannot_access_citation_endpoints(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    res = client.put(
        "/v1/admin/clients/tenant_a/uploads/doc.txt/citation",
        headers={"x-client-key": "wk_test_default"},
        json={"citation_url": "https://example.com/doc", "source_visibility": "public"},
    )
    assert res.status_code == 401


def test_delete_upload_removes_mapping_entry(lifecycle_env) -> None:
    client = lifecycle_env["client"]
    clients_root = lifecycle_env["clients_root"]
    config_dir = clients_root / "tenant_a" / "config"
    save_yaml(
        str(config_dir / "source_whitelist.yaml"),
        {"allowed_public_domains": ["example.com"]},
    )
    target = clients_root / "tenant_a" / "uploads" / "gone.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")
    client.put(
        "/v1/admin/clients/tenant_a/uploads/gone.txt/citation",
        headers=ADMIN_HEADERS,
        json={"citation_url": "https://example.com/gone", "source_visibility": "public"},
    )
    res = client.delete("/v1/admin/clients/tenant_a/uploads/gone.txt", headers=ADMIN_HEADERS)
    assert res.status_code == 204
    mapping = load_yaml(str(config_dir / "source_mapping.yaml"))
    assert "gone.txt" not in (mapping.get("uploads") or {})
