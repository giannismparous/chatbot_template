from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.worker.jobs.migrate_registry_to_firestore import migrate_registry_to_firestore
from packages.adapters.auth.firestore_widget_auth import FirestoreWidgetAuthProvider
from packages.adapters.firestore.in_memory_backend import InMemoryFirestoreBackend
from packages.adapters.firestore.in_memory_stores import (
    InMemoryClientRegistryStore,
    InMemoryConfigMetaStore,
    InMemoryJobStore,
    generate_widget_key_with_secret,
)
from packages.core.admin.config_service import ConfigService
from packages.core.control_plane.widget_key_hmac import (
    compute_widget_key_hash,
    verify_widget_key_hash,
    widget_key_lookup_prefix,
)
from packages.core.jobs.firestore_runner import FirestoreJobRunner
from packages.core.jobs.models import JobRecord, JobStatus, JobType
from packages.core.stack.factory import validate_stack_security
from packages.core.storage.tenant_storage import TenantStorage
from packages.core.tenant.errors import OriginNotAllowedError, WidgetKeyNotFoundError


SECRET = b"test-widget-hash-secret"


@pytest.fixture
def firestore_backend() -> InMemoryFirestoreBackend:
    return InMemoryFirestoreBackend()


@pytest.fixture
def registry_store(firestore_backend: InMemoryFirestoreBackend) -> InMemoryClientRegistryStore:
    return InMemoryClientRegistryStore(firestore_backend, hash_secret=SECRET)


@pytest.fixture
def config_meta_store(firestore_backend: InMemoryFirestoreBackend) -> InMemoryConfigMetaStore:
    return InMemoryConfigMetaStore(firestore_backend)


@pytest.fixture
def job_store(firestore_backend: InMemoryFirestoreBackend) -> InMemoryJobStore:
    return InMemoryJobStore(firestore_backend)


def test_hmac_hash_and_verify():
    full, prefix, digest = generate_widget_key_with_secret(SECRET)
    assert prefix == widget_key_lookup_prefix(full)
    assert verify_widget_key_hash(full, digest, secret=SECRET)
    assert not verify_widget_key_hash(full + "x", digest, secret=SECRET)


def test_wrong_key_fails_auth(registry_store: InMemoryClientRegistryStore):
    created = registry_store.create_client_record(
        client_id="tenant_a",
        display_name="Tenant A",
        domain_pack="generic",
        allowed_origins=["http://localhost:5173"],
        reveal_widget_key=True,
    )
    assert created.widget_key
    auth = FirestoreWidgetAuthProvider(registry_store, hash_secret=SECRET)
    assert auth.resolve_widget_key(created.widget_key, "http://localhost:5173") == "tenant_a"
    with pytest.raises(WidgetKeyNotFoundError):
        auth.resolve_widget_key("wk_invalid_key_value", "http://localhost:5173")


def test_revoked_key_fails(registry_store: InMemoryClientRegistryStore):
    created = registry_store.create_client_record(
        client_id="tenant_a",
        display_name="Tenant A",
        domain_pack="generic",
        allowed_origins=[],
        reveal_widget_key=True,
    )
    assert created.widget_key
    keys = registry_store.list_widget_keys("tenant_a")
    registry_store.revoke_widget_key("tenant_a", keys[0]["key_id"])
    auth = FirestoreWidgetAuthProvider(registry_store, hash_secret=SECRET)
    with pytest.raises(WidgetKeyNotFoundError):
        auth.resolve_widget_key(created.widget_key, None)


def test_prefix_collision_verifies_correct_hmac(registry_store: InMemoryClientRegistryStore):
    key_a = "wk_abcdefghijklmnop"
    key_b = "wk_abcdefghijxyzab"
    prefix = widget_key_lookup_prefix(key_a)
    assert widget_key_lookup_prefix(key_b) == prefix
    hash_a = compute_widget_key_hash(key_a, secret=SECRET)
    hash_b = compute_widget_key_hash(key_b, secret=SECRET)
    now = datetime.now(timezone.utc).isoformat()
    backend = registry_store._backend
    backend.upsert_client(
        "tenant_a",
        {
            "client_id": "tenant_a",
            "display_name": "A",
            "status": "active",
            "domain_pack": "generic",
            "config_revision": 0,
            "created_at": now,
            "updated_at": now,
        },
    )
    backend.upsert_client(
        "tenant_b",
        {
            "client_id": "tenant_b",
            "display_name": "B",
            "status": "active",
            "domain_pack": "generic",
            "config_revision": 0,
            "created_at": now,
            "updated_at": now,
        },
    )
    backend.upsert_widget_key(
        "tenant_a",
        "tenant_a_widget_1",
        {
            "key_id": "tenant_a_widget_1",
            "key_prefix": prefix,
            "key_hash": hash_a,
            "hash_alg": "hmac-sha256-v1",
            "allowed_origins": [],
            "status": "active",
            "created_at": now,
            "revoked_at": None,
        },
    )
    backend.upsert_widget_key(
        "tenant_b",
        "tenant_b_widget_1",
        {
            "key_id": "tenant_b_widget_1",
            "key_prefix": prefix,
            "key_hash": hash_b,
            "hash_alg": "hmac-sha256-v1",
            "allowed_origins": [],
            "status": "active",
            "created_at": now,
            "revoked_at": None,
        },
    )
    auth = FirestoreWidgetAuthProvider(registry_store, hash_secret=SECRET)
    assert auth.resolve_widget_key(key_a, None) == "tenant_a"
    assert auth.resolve_widget_key(key_b, None) == "tenant_b"


def test_create_returns_full_key_once(registry_store: InMemoryClientRegistryStore):
    hidden = registry_store.create_client_record(
        client_id="tenant_hidden",
        display_name="Hidden",
        domain_pack="generic",
        allowed_origins=[],
        reveal_widget_key=False,
    )
    assert hidden.widget_key is None


def test_list_never_returns_full_key(registry_store: InMemoryClientRegistryStore):
    created = registry_store.create_client_record(
        client_id="tenant_a",
        display_name="Tenant A",
        domain_pack="generic",
        allowed_origins=[],
        reveal_widget_key=True,
    )
    keys = registry_store.list_widget_keys("tenant_a")
    blob = str(keys)
    assert created.widget_key
    assert created.widget_key not in blob


def test_rotation_revokes_old_and_returns_new_key(registry_store: InMemoryClientRegistryStore):
    created = registry_store.create_client_record(
        client_id="tenant_a",
        display_name="Tenant A",
        domain_pack="generic",
        allowed_origins=["http://localhost:5173"],
        reveal_widget_key=True,
    )
    assert created.widget_key
    auth = FirestoreWidgetAuthProvider(registry_store, hash_secret=SECRET)
    rotated = registry_store.rotate_widget_key("tenant_a")
    assert rotated.widget_key
    assert rotated.widget_key != created.widget_key
    with pytest.raises(WidgetKeyNotFoundError):
        auth.resolve_widget_key(created.widget_key, "http://localhost:5173")
    assert auth.resolve_widget_key(rotated.widget_key, "http://localhost:5173") == "tenant_a"


def test_origin_binding_enforced(registry_store: InMemoryClientRegistryStore):
    created = registry_store.create_client_record(
        client_id="tenant_a",
        display_name="Tenant A",
        domain_pack="generic",
        allowed_origins=["https://example.com"],
        reveal_widget_key=True,
    )
    auth = FirestoreWidgetAuthProvider(registry_store, hash_secret=SECRET)
    assert auth.resolve_widget_key(created.widget_key, "https://example.com") == "tenant_a"
    with pytest.raises(OriginNotAllowedError):
        auth.resolve_widget_key(created.widget_key, "https://evil.com")


def test_config_put_writes_blob_and_metadata(
    tmp_path: Path,
    registry_store: InMemoryClientRegistryStore,
    config_meta_store: InMemoryConfigMetaStore,
):
    clients_root = tmp_path / "clients"
    config_dir = clients_root / "tenant_a" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "client.yaml").write_text("client_id: tenant_a\n", encoding="utf-8")
    now = datetime.now(timezone.utc).isoformat()
    registry_store._backend.upsert_client(
        "tenant_a",
        {
            "client_id": "tenant_a",
            "display_name": "Tenant A",
            "status": "active",
            "domain_pack": "generic",
            "config_revision": 0,
            "created_at": now,
            "updated_at": now,
        },
    )
    storage = TenantStorage.local(clients_root)
    service = ConfigService(
        clients_root=clients_root,
        tenant_storage=storage,
        config_meta_store=config_meta_store,
        registry_store=registry_store,
    )
    service.put_config("tenant_a", "locale", {"default_language": "el"})
    meta = config_meta_store.get_meta("tenant_a", "locale")
    assert meta is not None
    assert meta.revision == 1
    assert registry_store.get_config_revision("tenant_a") == 1
    assert storage.exists("tenant_a", "config/locale.yaml")


def test_job_store_lifecycle(job_store: InMemoryJobStore, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_JOBS_SYNC", "true")
    runner = FirestoreJobRunner(job_store=job_store)
    transitions: list[JobStatus] = []
    original_create = job_store.create
    original_update = job_store.update

    def tracking_create(record: JobRecord) -> JobRecord:
        transitions.append(record.status)
        return original_create(record)

    def tracking_update(record: JobRecord) -> None:
        transitions.append(record.status)
        original_update(record)

    monkeypatch.setattr(job_store, "create", tracking_create)
    monkeypatch.setattr(job_store, "update", tracking_update)

    record = runner.submit(
        client_id="tenant_a",
        job_type=JobType.INGEST,
        runner=lambda: {"ok": True},
    )
    assert transitions == [JobStatus.PENDING, JobStatus.RUNNING, JobStatus.SUCCEEDED]
    assert record.status == JobStatus.SUCCEEDED
    final = runner.get_job("tenant_a", record.job_id)
    assert final is not None
    assert final.status == JobStatus.SUCCEEDED


def test_firebase_validation_requires_widget_hash_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "secret")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo")
    monkeypatch.setenv("FIRESTORE_CONTROL_PLANE", "true")
    monkeypatch.delenv("WIDGET_KEY_HASH_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="WIDGET_KEY_HASH_SECRET"):
        validate_stack_security("firebase")


def test_migration_dry_run_no_secrets_logged(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "clients:\n  default:\n    display_name: Default\n    widget_keys:\n"
        "      - key_id: default_widget_1\n        public_key: wk_test_secret_key_value\n"
        "        allowed_origins: []\n",
        encoding="utf-8",
    )
    plan = migrate_registry_to_firestore(source_path=registry, dry_run=True, hash_secret=SECRET)
    output = capsys.readouterr().out
    assert "wk_test_secret_key_value" not in output
    assert plan["widget_key_count"] == 1


def test_migration_apply_writes_hash_only(
    firestore_backend: InMemoryFirestoreBackend, tmp_path: Path
):
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "clients:\n  default:\n    display_name: Default\n    widget_keys:\n"
        "      - key_id: default_widget_1\n        public_key: wk_test_secret_key_value\n"
        "        allowed_origins: []\n",
        encoding="utf-8",
    )
    migrate_registry_to_firestore(
        source_path=registry,
        dry_run=False,
        hash_secret=SECRET,
        backend=firestore_backend,
    )
    doc = firestore_backend.get_widget_key("default", "default_widget_1")
    assert doc is not None
    assert "public_key" not in doc
    assert doc["key_hash"].startswith("hmac-sha256-v1:")
    assert verify_widget_key_hash("wk_test_secret_key_value", doc["key_hash"], secret=SECRET)
