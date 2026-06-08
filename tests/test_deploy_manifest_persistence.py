from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from apps.worker.jobs.activate_index import activate_index
from apps.worker.jobs.rollback_index import rollback_index
from packages.adapters.storage.gcs_file_store import GcsFileStore
from packages.core.ingestion.models import ActiveManifest
from packages.core.stack.factory import project_root
from packages.core.storage.keys import gcs_object_name

ACTIVE_VERSION = "2026-06-07T063659_0000"
PENDING_VERSION = "2026-06-07T232651_0000"
PREVIOUS_VERSION = "2026-06-07T045340_0000"


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


def test_activate_index_persists_manifest_to_gcs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.core.stack import factory

    cache = tmp_path / "cache"
    manifest = {
        "active": ACTIVE_VERSION,
        "pending": PENDING_VERSION,
        "previous": PREVIOUS_VERSION,
    }
    objects = {
        gcs_object_name("default", "indexes/active_manifest.json"): (
            json.dumps(manifest, indent=2) + "\n"
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

    activated = activate_index(clients_root=cache, client_id="default")
    assert activated == PENDING_VERSION

    blob_key = gcs_object_name("default", "indexes/active_manifest.json")
    assert blob_key.startswith("clients/default/indexes/active_manifest.json")
    written = json.loads(objects[blob_key].decode("utf-8"))
    assert written["active"] == PENDING_VERSION
    assert written["previous"] == ACTIVE_VERSION
    assert "pending" not in written

    on_disk = json.loads((cache / "default" / "indexes" / "active_manifest.json").read_text(encoding="utf-8"))
    assert on_disk["active"] == PENDING_VERSION
    assert on_disk["previous"] == ACTIVE_VERSION
    assert "pending" not in on_disk


def test_rollback_index_persists_manifest_to_canonical_gcs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.core.stack import factory

    cache = tmp_path / "cache"
    manifest = {
        "active": ACTIVE_VERSION,
        "pending": None,
        "previous": PREVIOUS_VERSION,
    }
    objects = {
        gcs_object_name("default", "indexes/active_manifest.json"): (
            json.dumps(manifest, indent=2) + "\n"
        ).encode(),
        gcs_object_name("default", f"indexes/versions/{PREVIOUS_VERSION}/knowledge_index.json"): (
            b'{"client_id":"default","version_id":"%b","chunks":[{"id":"c1","content":"ok","title":"t"}]}\n'
            % PREVIOUS_VERSION.encode("utf-8")
        ),
        gcs_object_name("default", f"indexes/versions/{PREVIOUS_VERSION}/source_manifest.json"): (
            b'{"client_id":"default","version_id":"%b","sources":[{"source_id":"s1"}]}\n'
            % PREVIOUS_VERSION.encode("utf-8")
        ),
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

    activated = rollback_index(clients_root=cache, client_id="default")
    assert activated == PREVIOUS_VERSION

    blob_key = gcs_object_name("default", "indexes/active_manifest.json")
    assert blob_key.startswith("clients/default/indexes/active_manifest.json")
    written = json.loads(objects[blob_key].decode("utf-8"))
    assert written["active"] == PREVIOUS_VERSION
    assert written.get("previous") is None
    assert written.get("pending") is None


def test_activate_index_local_storage_still_updates_manifest(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    manifest_path = clients_root / "default" / "indexes" / "active_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            ActiveManifest(
                active=ACTIVE_VERSION,
                pending=PENDING_VERSION,
                previous=PREVIOUS_VERSION,
            ).to_dict(),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    activated = activate_index(clients_root=clients_root, client_id="default")
    assert activated == PENDING_VERSION

    written = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert written["active"] == PENDING_VERSION
    assert written["previous"] == ACTIVE_VERSION
    assert "pending" not in written
