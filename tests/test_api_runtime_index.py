from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from packages.adapters.storage.gcs_file_store import GcsFileStore
from packages.core.config.loader import TenantConfigLoader
from packages.core.ingestion.manifest import read_active_manifest
from packages.core.ingestion.paths import active_manifest_path, knowledge_index_path
from packages.core.retrieval.index_loader import load_tenant_index
from packages.core.stack.factory import project_root
from packages.core.storage.api_runtime_hydrator import (
    hydrate_client_active_index_for_runtime,
    prepare_firebase_api_runtime_index,
)
from packages.core.storage.keys import gcs_object_name
from packages.core.tenant.paths import client_config_dir

MINIMAL_CLIENT_YAML = b"""client_id: default
display_name: POAMSKP
domain_pack: generic
default_mode: hybrid_local
modes:
  - hybrid_local
source_weights: {}
"""

ACTIVE_VERSION = "2026-06-08T051814_0000"
LEGACY_STALE_VERSION = "2026-06-07T232651_0000"
POAMSKP_CHUNK_CONTENT = (
    "Η Πανελλήνια Ομοσπονδία Ατόμων με Σκλήρυνση Κατά Πλάκας (ΠΟΑμΣΚΠ) "
    "είναι η εθνική ομοσπονδία για τη σκλήρυνση κατά πλάκας στην Ελλάδα."
)
ACTIVE_MANIFEST = json.dumps(
    {"active": ACTIVE_VERSION, "pending": None, "previous": None},
    ensure_ascii=False,
).encode("utf-8")
KNOWLEDGE_INDEX = json.dumps(
    {
        "client_id": "default",
        "version_id": ACTIVE_VERSION,
        "chunks": [
            {
                "id": "poamskp-intro",
                "source_id": "poamskp_drive",
                "title": "ΠΟΑμΣΚΠ",
                "content": POAMSKP_CHUNK_CONTENT,
                "language": "el",
            }
        ],
    },
    ensure_ascii=False,
).encode("utf-8")
SOURCE_MANIFEST = json.dumps(
    {
        "version_id": ACTIVE_VERSION,
        "sources": [{"id": "poamskp_drive", "title": "POAMSKP Drive"}],
    },
    ensure_ascii=False,
).encode("utf-8")
VECTOR_INDEX = b'{"vectors":[],"embedding_model":"gemini-embedding-001","embedding_dims":768}\n'
INGEST_REPORT = json.dumps(
    {"version_id": ACTIVE_VERSION, "chunks_total": 1, "sources_total": 1},
).encode("utf-8")
MINIMAL_FAQ = json.dumps(
    {
        "entries": [
            {
                "id": "faq-poamskp-contact",
                "question": "Πώς μπορώ να επικοινωνήσω με την ΠΟΑμΣΚΠ;",
                "triggers": ["επικοινωνία", "επικοινων", "contact"],
                "answer": "Email: poamskp@otenet.gr. Τηλέφωνο: 213 022 2777.",
                "language": "el",
            }
        ]
    },
    ensure_ascii=False,
).encode("utf-8")


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

        blob.download_to_filename.side_effect = download_to_filename
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


def _canonical_index_objects() -> dict[str, bytes]:
    version_prefix = f"indexes/versions/{ACTIVE_VERSION}"
    return {
        gcs_object_name("default", "config/client.yaml"): MINIMAL_CLIENT_YAML,
        gcs_object_name("default", "config/faq.json"): MINIMAL_FAQ,
        gcs_object_name("default", "indexes/active_manifest.json"): ACTIVE_MANIFEST,
        gcs_object_name("default", f"{version_prefix}/knowledge_index.json"): KNOWLEDGE_INDEX,
        gcs_object_name("default", f"{version_prefix}/source_manifest.json"): SOURCE_MANIFEST,
        gcs_object_name("default", f"{version_prefix}/vector_index.json"): VECTOR_INDEX,
        gcs_object_name("default", f"{version_prefix}/ingest_report.json"): INGEST_REPORT,
    }


def _legacy_stale_index_objects() -> dict[str, bytes]:
    version_prefix = f"indexes/versions/{LEGACY_STALE_VERSION}"
    return {
        f"default/indexes/active_manifest.json": json.dumps(
            {"active": LEGACY_STALE_VERSION, "pending": None, "previous": None},
            ensure_ascii=False,
        ).encode("utf-8"),
        f"default/{version_prefix}/knowledge_index.json": json.dumps(
            {
                "client_id": "default",
                "version_id": LEGACY_STALE_VERSION,
                "chunks": [
                    {
                        "id": "legacy-stale",
                        "source_id": "legacy",
                        "title": "legacy",
                        "content": "legacy stale index that should not be used",
                        "language": "en",
                    }
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8"),
    }


def _firebase_env(monkeypatch: pytest.MonkeyPatch, cache: Path) -> None:
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


def test_hydrate_active_index_from_canonical_gcs_only(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    store = _make_gcs_store(cache, _canonical_index_objects())
    assert not active_manifest_path(cache, "default").is_file()

    report = hydrate_client_active_index_for_runtime(
        client_id="default",
        file_store=store,
        force=True,
    )

    manifest = read_active_manifest(active_manifest_path(cache, "default"))
    assert manifest.active == ACTIVE_VERSION
    assert knowledge_index_path(cache, "default", ACTIVE_VERSION).is_file()
    assert report.active_version == ACTIVE_VERSION
    assert report.chunk_count == 1
    assert report.source_count == 1
    assert report.knowledge_index_exists is True
    assert "clients/default/indexes" in report.gcs_manifest_key

    index = load_tenant_index(
        clients_root=cache,
        client_id="default",
        legacy_fallback_path=project_root() / "packages" / "config" / "defaults" / "knowledge.json",
    )
    assert index.is_legacy is False
    assert index.version_id == ACTIVE_VERSION
    assert len(index.chunks) == 1
    assert "ΠΟΑμΣΚΠ" in index.chunks[0].content


def test_api_runtime_prefers_canonical_when_legacy_is_stale(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    objects = _canonical_index_objects()
    objects.update(_legacy_stale_index_objects())
    store = _make_gcs_store(cache, objects)

    report = hydrate_client_active_index_for_runtime(
        client_id="default",
        file_store=store,
        force=True,
    )
    assert report.active_version == ACTIVE_VERSION
    assert report.knowledge_index_exists is True

    index = load_tenant_index(
        clients_root=cache,
        client_id="default",
        legacy_fallback_path=project_root() / "packages" / "config" / "defaults" / "knowledge.json",
    )
    assert index.version_id == ACTIVE_VERSION
    assert len(index.chunks) == 1
    assert "legacy stale index" not in index.chunks[0].content.lower()


def test_firebase_api_runtime_retrieves_poamskp_chunk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.dependencies import stack as stack_module
    from apps.api.dependencies.container import build_orchestrator, build_tenant_config_loader
    from packages.core.stack import factory

    cache = tmp_path / "cache"
    gcs_store = _make_gcs_store(cache, _canonical_index_objects())
    _firebase_env(monkeypatch, cache)
    monkeypatch.setattr(factory, "build_file_store", lambda profile, stack_yaml, root: gcs_store)

    stack_module.reset_stack()
    loader = build_tenant_config_loader()
    orchestrator = build_orchestrator(loader)

    chunks = orchestrator._retriever.retrieve(
        "Τι είναι η ΠΟΑμΣΚΠ;",
        client_id="default",
        limit=6,
        mode="hybrid_local",
    )
    assert chunks
    combined = " ".join(c.text for c in chunks)
    assert "ΠΟΑμΣΚΠ" in combined or "ποαμσκπ" in combined.lower()

    contact_chunks = orchestrator._retriever.retrieve(
        "Πώς μπορώ να επικοινωνήσω με την ΠΟΑμΣΚΠ;",
        client_id="default",
        limit=6,
        mode="hybrid_local",
    )
    assert contact_chunks
    contact_text = " ".join(c.text for c in contact_chunks).lower()
    assert "poamskp" in contact_text or "213" in contact_text


def test_prepare_firebase_api_runtime_index_hydrates_config_and_active_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.dependencies import stack as stack_module
    from packages.core.stack import factory

    cache = tmp_path / "cache"
    gcs_store = _make_gcs_store(cache, _canonical_index_objects())
    _firebase_env(monkeypatch, cache)
    monkeypatch.setattr(factory, "build_file_store", lambda profile, stack_yaml, root: gcs_store)

    stack_module.reset_stack()
    stack = stack_module.get_stack()
    report = prepare_firebase_api_runtime_index(client_id="default", stack=stack)

    assert (client_config_dir(cache, "default") / "client.yaml").is_file()
    assert report.active_version == ACTIVE_VERSION
    assert report.chunk_count == 1
    assert report.source_count == 1
    assert report.skipped_reason is None
