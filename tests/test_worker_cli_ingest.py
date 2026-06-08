from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apps.worker.cli import cmd_ingest, main
from packages.adapters.storage.gcs_file_store import GcsFileStore
from packages.config.loaders import save_yaml
from packages.core.drive_sources.config import add_drive_source
from packages.core.stack.factory import project_root
from packages.core.storage.keys import gcs_object_name

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"

DRIVE_TEXT = (
    "SimasiaAI builds Greek chatbots for regulated domains with source-backed answers "
    "and safety guardrails for public sector and healthcare deployments."
)


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


def _seed_gcs_objects(config_dir: Path) -> dict[str, bytes]:
    manifest = {
        "updated_at": "2026-06-08T00:00:00Z",
        "sources": {
            "poamskp_drive": {
                "status": "synced",
                "files_discovered": 1,
                "files_synced": 1,
                "files": {
                    "file1": {
                        "file_id": "file1",
                        "name": "faq.txt",
                        "mime_type": "text/plain",
                        "status": "synced",
                        "cache_file": "faq_file1.txt",
                        "char_count": len(DRIVE_TEXT),
                    }
                },
            }
        },
    }
    return {
        gcs_object_name("default", "config/client.yaml"): (
            b"client_id: default\ndisplay_name: Default\ndomain_pack: generic\n"
        ),
        gcs_object_name("default", "config/source_whitelist.yaml"): (
            b"allowed_public_domains:\n  - simasiaai.gr\n"
        ),
        gcs_object_name("default", "config/drive_sources.yaml"): (
            Path(config_dir / "drive_sources.yaml").read_bytes()
        ),
        gcs_object_name("default", "config/ingestion.yaml"): b"embed_enabled: false\n",
        gcs_object_name("default", "drive_cache/drive_sync_manifest.json"): (
            json.dumps(manifest, indent=2) + "\n"
        ).encode(),
        gcs_object_name("default", "drive_cache/files/poamskp_drive/faq_file1.txt"): DRIVE_TEXT.encode(
            "utf-8"
        ),
    }


def _configure_firebase_env(cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STACK_PROFILE", "firebase")
    monkeypatch.setenv("FIRESTORE_CONTROL_PLANE", "false")
    monkeypatch.setenv("GCS_REGISTRY_FALLBACK", "true")
    monkeypatch.setenv("ADMIN_API_TOKEN", "secret")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo")
    monkeypatch.setenv("GCS_BUCKET", "simasia-chatbot-prod-demo")
    monkeypatch.setenv("TENANT_CACHE_ROOT", str(cache))
    monkeypatch.setenv("APP_GIT_SHA", "test-sha")
    monkeypatch.setenv(
        "CLIENT_REGISTRY_PATH",
        str(project_root() / "tests" / "fixtures" / "registry.yaml"),
    )


def test_worker_cli_ingest_hydrates_drive_cache_and_indexes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from argparse import Namespace
    from packages.core.stack import factory

    cache = tmp_path / "cache"
    config_dir = cache / "default" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    save_yaml(
        str(config_dir / "client.yaml"),
        {"client_id": "default", "display_name": "Default", "domain_pack": "generic"},
    )
    save_yaml(str(config_dir / "source_whitelist.yaml"), {"allowed_public_domains": ["simasiaai.gr"]})
    add_drive_source(
        config_dir,
        folder_id="folder123456789",
        title="POAMSKP Drive",
        enabled=True,
        recursive=False,
        max_files=50,
        source_id="poamskp_drive",
    )

    objects = _seed_gcs_objects(config_dir)
    gcs_store = _make_gcs_store(cache, objects)
    _configure_firebase_env(cache, monkeypatch)
    monkeypatch.setattr(factory, "build_file_store", lambda profile, stack_yaml, root: gcs_store)

    assert not (cache / "default" / "drive_cache" / "drive_sync_manifest.json").exists()
    code = cmd_ingest(Namespace(client_id="default", version_id=None))
    assert code == 0

    output = capsys.readouterr().out
    assert "[ingest-prep] STACK_PROFILE=firebase" in output
    assert "[ingest-prep] drive_manifest_exists=True" in output
    assert "[ingest-prep] hydrated drive_cache_blobs=" in output
    assert "[drive-ingest]" in output
    assert "indexable=1" in output
    assert "sources=0->1" in output or "sources=0->2" in output
    assert "Ingest complete for default" in output
    assert "sources=1" in output or "sources=2" in output

    versions = list((cache / "default" / "indexes" / "versions").iterdir())
    assert versions
    report = json.loads((versions[0] / "ingest_report.json").read_text(encoding="utf-8"))
    assert report["sources_total"] > 0
    assert report["chunks_total"] > 0


def test_worker_cli_main_ingest_entrypoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.core.stack import factory

    cache = tmp_path / "cache"
    config_dir = cache / "default" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    save_yaml(
        str(config_dir / "client.yaml"),
        {"client_id": "default", "display_name": "Default", "domain_pack": "generic"},
    )
    add_drive_source(
        config_dir,
        folder_id="folder123456789",
        title="POAMSKP Drive",
        enabled=True,
        recursive=False,
        max_files=50,
        source_id="poamskp_drive",
    )
    objects = _seed_gcs_objects(config_dir)
    gcs_store = _make_gcs_store(cache, objects)
    _configure_firebase_env(cache, monkeypatch)
    monkeypatch.setattr(factory, "build_file_store", lambda profile, stack_yaml, root: gcs_store)

    with pytest.raises(SystemExit) as exc:
        main(["job", "ingest", "--client-id", "default"])
    assert exc.value.code == 0
