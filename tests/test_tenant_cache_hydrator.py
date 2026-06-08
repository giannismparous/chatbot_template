from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from packages.adapters.firestore.in_memory_backend import InMemoryFirestoreBackend
from packages.adapters.firestore.in_memory_stores import InMemoryConfigMetaStore
from packages.adapters.storage.gcs_file_store import GcsFileStore
from packages.core.control_plane.models import ConfigMetaRecord
from packages.core.config.loader import TenantConfigLoader
from packages.core.stack.factory import project_root
from packages.core.storage.keys import gcs_object_name, gcs_object_name_candidates
from packages.core.eval.index_scope import eval_index_scope
from packages.core.ingestion.manifest import read_active_manifest
from packages.core.ingestion.paths import active_manifest_path, knowledge_index_path
from packages.core.storage.tenant_cache_hydrator import (
    hydrate_client_config,
    hydrate_client_eval_assets,
    hydrate_client_index_state,
)
from packages.core.eval.loader import load_eval_suite, load_eval_cases
from packages.core.tenant.paths import client_config_dir

MINIMAL_CLIENT_YAML = b"""client_id: default
display_name: Default
domain_pack: generic
default_mode: hybrid_local
modes:
  - hybrid_local
source_weights: {}
"""


def _make_gcs_store(cache_root: Path, objects: dict[str, bytes]) -> GcsFileStore:
    bucket = MagicMock()

    def _blob(name: str) -> MagicMock:
        blob = MagicMock()
        blob.name = name
        blob.exists.side_effect = lambda: name in objects
        blob.size = len(objects.get(name, b""))

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


def test_gcs_object_name_candidates_include_legacy_layout() -> None:
    names = gcs_object_name_candidates("default", "config/client.yaml")
    assert names[0] == "clients/default/config/client.yaml"
    assert "default/config/client.yaml" in names


def test_hydrate_client_config_from_canonical_gcs_path(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    store = _make_gcs_store(
        cache,
        {gcs_object_name("default", "config/client.yaml"): MINIMAL_CLIENT_YAML},
    )
    count = hydrate_client_config(client_id="default", file_store=store)
    config_dir = client_config_dir(cache, "default")
    assert count >= 1
    assert (config_dir / "client.yaml").is_file()
    assert (config_dir / "client.yaml").read_bytes() == MINIMAL_CLIENT_YAML


def test_hydrate_client_config_from_legacy_gcs_path(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    store = _make_gcs_store(cache, {"default/config/client.yaml": MINIMAL_CLIENT_YAML})
    hydrate_client_config(client_id="default", file_store=store)
    assert (client_config_dir(cache, "default") / "client.yaml").is_file()


def test_hydrate_uses_firestore_metadata_storage_keys(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    store = _make_gcs_store(
        cache,
        {
            gcs_object_name("default", "config/client.yaml"): MINIMAL_CLIENT_YAML,
            gcs_object_name("default", "config/locale.yaml"): b"default_language: el\n",
        },
    )
    backend = InMemoryFirestoreBackend()
    meta_store = InMemoryConfigMetaStore(backend)
    now = datetime.now(timezone.utc)
    for key, storage_key, digest in (
        ("client", "config/client.yaml", "a"),
        ("locale", "config/locale.yaml", "b"),
    ):
        meta_store.put_meta(
            ConfigMetaRecord(
                client_id="default",
                config_key=key,
                storage_key=storage_key,
                content_sha256=digest,
                size_bytes=1,
                content_type="application/x-yaml",
                revision=1,
                updated_at=now,
            )
        )
    hydrate_client_config(
        client_id="default",
        file_store=store,
        config_meta_store=meta_store,
    )
    assert (client_config_dir(cache, "default") / "locale.yaml").is_file()


def test_hydrate_then_config_loader_succeeds_with_empty_cache(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    store = _make_gcs_store(
        cache,
        {gcs_object_name("default", "config/client.yaml"): MINIMAL_CLIENT_YAML},
    )
    assert not client_config_dir(cache, "default").is_dir()
    hydrate_client_config(client_id="default", file_store=store)
    loader = TenantConfigLoader(
        clients_root=store.get_local_clients_root(),
        domain_packs_root=project_root() / "packages" / "domain_packs",
    )
    merged = loader.load("default")
    assert merged.client_id == "default"


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


def test_hydrate_eval_assets_from_gcs(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    store = _make_gcs_store(
        cache,
        {
            gcs_object_name("default", "tests/eval_suite.yaml"): MINIMAL_EVAL_SUITE,
            gcs_object_name("default", "tests/cases/smoke.yaml"): MINIMAL_EVAL_CASE,
            gcs_object_name("default", "tests/output/eval_report.json"): b'{"status":"pass"}',
        },
    )
    count = hydrate_client_eval_assets(client_id="default", file_store=store)
    assert count >= 2
    assert not (cache / "default" / "tests" / "output" / "eval_report.json").exists()
    suite = load_eval_suite(cache, "default")
    assert suite.client_id == "default"
    cases = load_eval_cases(cache, "default")
    assert any(case.id == "smoke_answer" for case in cases)


def test_ensure_firebase_eval_hydration_loads_suite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.core.stack import factory
    from packages.core.storage.tenant_cache_hydrator import ensure_firebase_eval_assets_hydrated

    cache = tmp_path / "cache"
    gcs_store = _make_gcs_store(
        cache,
        {
            gcs_object_name("default", "config/client.yaml"): MINIMAL_CLIENT_YAML,
            gcs_object_name("default", "tests/eval_suite.yaml"): MINIMAL_EVAL_SUITE,
            gcs_object_name("default", "tests/cases/smoke.yaml"): MINIMAL_EVAL_CASE,
        },
    )

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

    ensure_firebase_eval_assets_hydrated(client_id="default")
    suite = load_eval_suite(cache, "default")
    assert suite.client_id == "default"
    assert (cache / "default" / "tests" / "cases" / "smoke.yaml").is_file()


def test_firebase_build_stack_hydrates_default_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.dependencies import stack as stack_module
    from packages.core.stack import factory

    cache = tmp_path / "cache"
    gcs_store = _make_gcs_store(
        cache,
        {gcs_object_name("default", "config/client.yaml"): MINIMAL_CLIENT_YAML},
    )

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

    stack_module.reset_stack()
    stack = stack_module.get_stack()
    assert stack.profile == "firebase"
    assert (client_config_dir(cache, "default") / "client.yaml").is_file()

    loader = TenantConfigLoader(
        clients_root=stack.config_store.get_clients_root(),
        domain_packs_root=project_root() / "packages" / "domain_packs",
    )
    merged = loader.load("default")
    assert merged.client_id == "default"


PENDING_VERSION = "2026-06-07T232651_0000"
ACTIVE_MANIFEST = (
    b'{"active": null, "pending": "'
    + PENDING_VERSION.encode()
    + b'", "previous": null}\n'
)
KNOWLEDGE_INDEX = (
    b'{"client_id":"default","version_id":"'
    + PENDING_VERSION.encode()
    + b'","chunks":[{"id":"c1","content":"hello","title":"t"}]}\n'
)
VECTOR_INDEX = b'{"vectors":[{"chunk_id":"c1","embedding":[0.1,0.2]}],"embedding_model":"test","embedding_dims":2}\n'


def test_hydrate_index_state_from_gcs(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    store = _make_gcs_store(
        cache,
        {
            gcs_object_name("default", "indexes/active_manifest.json"): ACTIVE_MANIFEST,
            gcs_object_name(
                "default",
                f"indexes/versions/{PENDING_VERSION}/knowledge_index.json",
            ): KNOWLEDGE_INDEX,
            gcs_object_name(
                "default",
                f"indexes/versions/{PENDING_VERSION}/vector_index.json",
            ): VECTOR_INDEX,
        },
    )
    assert not active_manifest_path(cache, "default").is_file()
    count = hydrate_client_index_state(client_id="default", file_store=store)
    assert count >= 3
    manifest = read_active_manifest(active_manifest_path(cache, "default"))
    assert manifest.pending == PENDING_VERSION
    assert knowledge_index_path(cache, "default", PENDING_VERSION).is_file()


def test_firebase_eval_hydration_enables_pending_index_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.core.stack import factory
    from packages.core.storage.tenant_cache_hydrator import ensure_firebase_eval_assets_hydrated

    cache = tmp_path / "cache"
    gcs_store = _make_gcs_store(
        cache,
        {
            gcs_object_name("default", "config/client.yaml"): MINIMAL_CLIENT_YAML,
            gcs_object_name("default", "tests/eval_suite.yaml"): MINIMAL_EVAL_SUITE,
            gcs_object_name("default", "tests/cases/smoke.yaml"): MINIMAL_EVAL_CASE,
            gcs_object_name("default", "indexes/active_manifest.json"): ACTIVE_MANIFEST,
            gcs_object_name(
                "default",
                f"indexes/versions/{PENDING_VERSION}/knowledge_index.json",
            ): KNOWLEDGE_INDEX,
            gcs_object_name(
                "default",
                f"indexes/versions/{PENDING_VERSION}/vector_index.json",
            ): VECTOR_INDEX,
        },
    )

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

    ensure_firebase_eval_assets_hydrated(client_id="default")
    with eval_index_scope(cache, "default", scope="pending") as scope:
        assert scope.version_id == PENDING_VERSION
        assert scope.manifest_path.is_file()
