from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packages.config.loaders import save_yaml
from packages.core.citations.context_builder import build_citation_context
from packages.core.citations.enforcer import enforce_citations
from packages.core.config.loader import TenantConfigLoader
from packages.core.domain.models import RetrievedChunk
from packages.core.drive_sources.citation import resolve_drive_citation
from packages.core.drive_sources.config import add_drive_source
from packages.core.drive_sources.extractor import extract_drive_bytes
from packages.core.drive_sources.manifest import empty_manifest
from packages.core.drive_sources.models import GOOGLE_DOC_MIME, DriveSyncSettings
from packages.core.drive_sources.service import sync_client_drive_sources
from packages.core.drive_sources.sync import DriveRemoteFile, MockDrivePort, sync_drive_source
from packages.core.ingestion.pipeline import ingest_client_uploads
from packages.core.ingestion.source_mapping import SourceMappingConfig, SourceMappingEntry

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"
ADMIN_HEADERS = {"x-admin-token": "test-admin-token"}

GOOD_TEXT = (
    "SimasiaAI builds Greek chatbots for regulated domains with source-backed answers "
    "and safety guardrails for public sector and healthcare deployments."
)


def _seed_tenant(tmp_path: Path) -> Path:
    clients_root = tmp_path / "clients"
    config_dir = clients_root / "tenant_a" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (clients_root / "tenant_a" / "uploads").mkdir(parents=True, exist_ok=True)
    (clients_root / "tenant_a" / "web_cache").mkdir(parents=True, exist_ok=True)
    (clients_root / "tenant_a" / "drive_cache").mkdir(parents=True, exist_ok=True)
    (clients_root / "tenant_a" / "indexes" / "versions").mkdir(parents=True, exist_ok=True)
    save_yaml(
        str(config_dir / "client.yaml"),
        {"client_id": "tenant_a", "display_name": "Tenant A", "domain_pack": "generic"},
    )
    save_yaml(str(config_dir / "source_whitelist.yaml"), {"allowed_public_domains": ["simasiaai.gr"]})
    save_yaml(str(config_dir / "web_sources.yaml"), {"version": 1, "sources": []})
    save_yaml(str(config_dir / "drive_sources.yaml"), {"version": 1, "sources": []})
    return clients_root


def _drive_source(folder_id: str = "folder123456789"):
    from packages.core.drive_sources.models import DriveSourceEntry

    return DriveSourceEntry(
        id="docs",
        folder_id=folder_id,
        title="Docs",
        enabled=True,
        recursive=False,
        max_files=10,
    )


def test_google_doc_export_extracts_text() -> None:
    text, err = extract_drive_bytes(
        data=GOOD_TEXT.encode("utf-8"),
        mime_type=GOOGLE_DOC_MIME,
        filename="FAQ",
    )
    assert err is None
    assert "SimasiaAI" in (text or "")


def test_mock_drive_sync_writes_cache(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    source = _drive_source()
    settings = DriveSyncSettings.from_dict({"drive_sync": {"max_file_bytes": 1_000_000}})
    manifest = empty_manifest()
    remote = DriveRemoteFile(
        file_id="file1",
        name="faq.txt",
        mime_type="text/plain",
        modified_time="2026-06-07T10:00:00.000Z",
        web_view_link="https://drive.google.com/file/d/file1/view",
    )
    port = MockDrivePort(
        files_by_folder={source.folder_id: [remote]},
        downloads={"file1": GOOD_TEXT.encode("utf-8")},
    )
    result = sync_drive_source(
        clients_root=clients_root,
        client_id="tenant_a",
        source=source,
        settings=settings,
        manifest=manifest,
        drive=port,
    )
    assert result.status == "synced"
    cache_dir = clients_root / "tenant_a" / "drive_cache" / "files" / "docs"
    assert list(cache_dir.glob("*.txt"))


def test_unchanged_file_skipped(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    source = _drive_source()
    settings = DriveSyncSettings.from_dict({"drive_sync": {}})
    manifest = empty_manifest()
    remote = DriveRemoteFile(
        file_id="file1",
        name="faq.txt",
        mime_type="text/plain",
        modified_time="2026-06-07T10:00:00.000Z",
        web_view_link="https://drive.google.com/x",
    )
    port = MockDrivePort(
        files_by_folder={source.folder_id: [remote]},
        downloads={"file1": GOOD_TEXT.encode("utf-8")},
    )
    sync_drive_source(
        clients_root=clients_root,
        client_id="tenant_a",
        source=source,
        settings=settings,
        manifest=manifest,
        drive=port,
    )
    port2 = MockDrivePort(files_by_folder={source.folder_id: [remote]}, downloads={})
    sync_drive_source(
        clients_root=clients_root,
        client_id="tenant_a",
        source=source,
        settings=settings,
        manifest=manifest,
        drive=port2,
    )
    assert manifest.sources["docs"].files["file1"].status == "skipped_unchanged"


def test_missing_credentials_failed_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_DRIVE_CREDENTIALS_JSON", raising=False)
    clients_root = _seed_tenant(tmp_path)
    config_dir = clients_root / "tenant_a" / "config"
    add_drive_source(
        config_dir,
        folder_id="folder123456789",
        title="Docs",
        enabled=True,
        recursive=False,
        max_files=10,
        source_id="docs",
    )
    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    result = sync_client_drive_sources(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=loader,
    )
    assert result["credentials_configured"] is False
    assert result["sources"][0]["status"] == "failed_auth"


def test_disabled_source_skipped(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    config_dir = clients_root / "tenant_a" / "config"
    add_drive_source(
        config_dir,
        folder_id="folder123456789",
        title="Docs",
        enabled=False,
        recursive=False,
        max_files=10,
        source_id="docs",
    )
    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    result = sync_client_drive_sources(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=loader,
        drive_port=MockDrivePort({}, {}),
    )
    assert result["sources"][0]["skipped"] is True


def test_trashed_and_size_limits(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    source = _drive_source()
    settings = DriveSyncSettings.from_dict({"drive_sync": {"max_file_bytes": 20}})
    manifest = empty_manifest()
    remotes = [
        DriveRemoteFile(
            file_id="trashed",
            name="t.txt",
            mime_type="text/plain",
            modified_time="2026-06-07T10:00:00.000Z",
            web_view_link="https://drive.google.com/x",
            trashed=True,
        ),
        DriveRemoteFile(
            file_id="big",
            name="big.txt",
            mime_type="text/plain",
            modified_time="2026-06-07T10:00:00.000Z",
            web_view_link="https://drive.google.com/x",
            size=9999,
        ),
    ]
    port = MockDrivePort(
        files_by_folder={source.folder_id: remotes},
        downloads={"big": GOOD_TEXT.encode("utf-8")},
    )
    sync_drive_source(
        clients_root=clients_root,
        client_id="tenant_a",
        source=source,
        settings=settings,
        manifest=manifest,
        drive=port,
    )
    assert manifest.sources["docs"].files["trashed"].status == "skipped_trashed"
    assert manifest.sources["docs"].files["big"].status == "failed_size"


def test_drive_cache_ingested_internal(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    config_dir = clients_root / "tenant_a" / "config"
    add_drive_source(
        config_dir,
        folder_id="folder123456789",
        title="Docs",
        enabled=True,
        recursive=False,
        max_files=10,
        source_id="docs",
    )
    cache_dir = clients_root / "tenant_a" / "drive_cache" / "files" / "docs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "faq_file1.txt").write_text(GOOD_TEXT, encoding="utf-8")
    manifest_path = clients_root / "tenant_a" / "drive_cache" / "drive_sync_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "sources": {
                    "docs": {
                        "status": "synced",
                        "files": {
                            "file1": {
                                "file_id": "file1",
                                "name": "faq.txt",
                                "mime_type": "text/plain",
                                "status": "synced",
                                "cache_file": "faq_file1.txt",
                                "char_count": len(GOOD_TEXT),
                            }
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    result = ingest_client_uploads(clients_root=clients_root, client_id="tenant_a", config_loader=loader)
    index = json.loads(
        (
            clients_root
            / "tenant_a"
            / "indexes"
            / "versions"
            / result.version_id
            / "knowledge_index.json"
        ).read_text(encoding="utf-8")
    )
    drive_chunks = [c for c in index["chunks"] if "internal://drive/" in c.get("internal_url", "")]
    assert drive_chunks
    assert drive_chunks[0]["source_visibility"] == "internal"
    assert "drive.google.com" not in json.dumps(index)


def test_mapped_whitelisted_drive_public() -> None:
    mapping = SourceMappingConfig(
        drive={
            "docs/faq_file1": SourceMappingEntry(
                citation_url="https://simasiaai.gr/",
                title="FAQ",
                source_visibility="public",
            )
        }
    )
    resolved = resolve_drive_citation(
        source_id="docs",
        file_key="faq_file1",
        title="faq.txt",
        mapping=mapping,
        whitelist={"allowed_public_domains": ["simasiaai.gr"]},
    )
    assert resolved.source_visibility == "public"
    assert resolved.citation_url == "https://simasiaai.gr/"


def test_drive_google_url_never_public() -> None:
    mapping = SourceMappingConfig(
        drive={
            "docs/faq_file1": SourceMappingEntry(
                citation_url="https://drive.google.com/file/d/abc/view",
                title="FAQ",
                source_visibility="public",
            )
        }
    )
    resolved = resolve_drive_citation(
        source_id="docs",
        file_key="faq_file1",
        title="faq.txt",
        mapping=mapping,
        whitelist={"allowed_public_domains": ["simasiaai.gr"]},
    )
    assert resolved.citation_url is None


def test_plaintext_and_markdown_extract() -> None:
    for mime, name in (("text/plain", "notes.txt"), ("text/markdown", "notes.md")):
        text, err = extract_drive_bytes(data=GOOD_TEXT.encode("utf-8"), mime_type=mime, filename=name)
        assert err is None
        assert "SimasiaAI" in (text or "")


def test_changed_modified_time_resyncs(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    source = _drive_source()
    settings = DriveSyncSettings.from_dict({"drive_sync": {}})
    manifest = empty_manifest()
    remote_v1 = DriveRemoteFile(
        file_id="file1",
        name="faq.txt",
        mime_type="text/plain",
        modified_time="2026-06-07T10:00:00.000Z",
        web_view_link="https://drive.google.com/x",
    )
    port_v1 = MockDrivePort(
        files_by_folder={source.folder_id: [remote_v1]},
        downloads={"file1": GOOD_TEXT.encode("utf-8")},
    )
    sync_drive_source(
        clients_root=clients_root,
        client_id="tenant_a",
        source=source,
        settings=settings,
        manifest=manifest,
        drive=port_v1,
    )
    updated_text = GOOD_TEXT + " Updated content for resync."
    remote_v2 = DriveRemoteFile(
        file_id="file1",
        name="faq.txt",
        mime_type="text/plain",
        modified_time="2026-06-07T11:00:00.000Z",
        web_view_link="https://drive.google.com/x",
    )
    port_v2 = MockDrivePort(
        files_by_folder={source.folder_id: [remote_v2]},
        downloads={"file1": updated_text.encode("utf-8")},
    )
    sync_drive_source(
        clients_root=clients_root,
        client_id="tenant_a",
        source=source,
        settings=settings,
        manifest=manifest,
        drive=port_v2,
    )
    record = manifest.sources["docs"].files["file1"]
    assert record.status == "synced"
    cache_path = clients_root / "tenant_a" / "drive_cache" / "files" / "docs" / record.cache_file
    assert "Updated content for resync." in cache_path.read_text(encoding="utf-8")


def test_max_files_per_source_enforced(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    source = _drive_source()
    source = source.__class__(**{**source.__dict__, "max_files": 2})
    settings = DriveSyncSettings.from_dict({"drive_sync": {}})
    manifest = empty_manifest()
    remotes = [
        DriveRemoteFile(
            file_id=f"f{i}",
            name=f"file{i}.txt",
            mime_type="text/plain",
            modified_time="2026-06-07T10:00:00.000Z",
            web_view_link="https://drive.google.com/x",
        )
        for i in range(5)
    ]
    port = MockDrivePort(
        files_by_folder={source.folder_id: remotes},
        downloads={f"f{i}": GOOD_TEXT.encode("utf-8") for i in range(5)},
    )
    sync_drive_source(
        clients_root=clients_root,
        client_id="tenant_a",
        source=source,
        settings=settings,
        manifest=manifest,
        drive=port,
    )
    synced = [f for f in manifest.sources["docs"].files.values() if f.status == "synced"]
    assert len(synced) == 2


def test_failed_extraction_creates_zero_chunks(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    source = _drive_source()
    settings = DriveSyncSettings.from_dict({"drive_sync": {}})
    manifest = empty_manifest()
    remote = DriveRemoteFile(
        file_id="badpdf",
        name="empty.pdf",
        mime_type="application/pdf",
        modified_time="2026-06-07T10:00:00.000Z",
        web_view_link="https://drive.google.com/x",
    )
    port = MockDrivePort(
        files_by_folder={source.folder_id: [remote]},
        downloads={"badpdf": b"not-a-valid-pdf"},
    )
    sync_drive_source(
        clients_root=clients_root,
        client_id="tenant_a",
        source=source,
        settings=settings,
        manifest=manifest,
        drive=port,
    )
    assert manifest.sources["docs"].files["badpdf"].status == "failed_extraction"
    config_dir = clients_root / "tenant_a" / "config"
    add_drive_source(
        config_dir,
        folder_id="folder123456789",
        title="Docs",
        enabled=True,
        recursive=False,
        max_files=10,
        source_id="docs",
    )
    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    result = ingest_client_uploads(clients_root=clients_root, client_id="tenant_a", config_loader=loader)
    index = json.loads(
        (
            clients_root
            / "tenant_a"
            / "indexes"
            / "versions"
            / result.version_id
            / "knowledge_index.json"
        ).read_text(encoding="utf-8")
    )
    drive_chunks = [c for c in index["chunks"] if "internal://drive/" in c.get("internal_url", "")]
    assert drive_chunks == []


def test_internal_drive_never_in_public_sources() -> None:
    chunk = RetrievedChunk(
        id="drive1",
        text="Drive-only content",
        source="internal://drive/docs/faq_file1",
        score=0.9,
        metadata={
            "title": "FAQ",
            "internal_url": "internal://drive/docs/faq_file1",
            "citation_url": "https://simasiaai.gr/",
            "source_visibility": "public",
        },
    )
    ctx = build_citation_context([chunk])
    whitelist = {"allowed_public_domains": ["simasiaai.gr"], "citation_url_rules": {"allow_only_whitelisted": True}}
    result = enforce_citations("Answer [1].", ctx, whitelist)
    assert result.public_sources[0].url == "https://simasiaai.gr/"
    assert "internal://drive" not in result.answer
    assert "drive.google.com" not in result.answer


def test_admin_drive_sources_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-admin-token")
    clients_root = _seed_tenant(tmp_path)
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text("clients: []\n", encoding="utf-8")
    monkeypatch.setenv("CLIENTS_ROOT", str(clients_root))
    monkeypatch.setenv("CLIENT_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("ADMIN_JOBS_SYNC", "true")
    from apps.api.dependencies import stack as stack_module

    stack_module.reset_stack()
    from apps.api.main import app

    client = TestClient(app)
    res = client.post(
        "/v1/admin/clients/tenant_a/drive-sources",
        headers=ADMIN_HEADERS,
        json={"folder_id": "folder123456789", "title": "Docs", "id": "docs"},
    )
    assert res.status_code == 201
    listed = client.get("/v1/admin/clients/tenant_a/drive-sources", headers=ADMIN_HEADERS)
    assert listed.status_code == 200
    assert listed.json()["sources"][0]["folder_id"] == "folder123456789"
    stack_module.reset_stack()


def test_partial_failures_use_synced_with_warnings(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    source = _drive_source()
    settings = DriveSyncSettings.from_dict({"drive_sync": {}})
    manifest = empty_manifest()
    remotes = [
        DriveRemoteFile(
            file_id="ok",
            name="faq.txt",
            mime_type="text/plain",
            modified_time="2026-06-07T10:00:00.000Z",
            web_view_link="https://drive.google.com/x",
        ),
        DriveRemoteFile(
            file_id="bad",
            name="broken.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            modified_time="2026-06-07T10:00:00.000Z",
            web_view_link="https://drive.google.com/x",
        ),
    ]
    port = MockDrivePort(
        files_by_folder={source.folder_id: remotes},
        downloads={"ok": GOOD_TEXT.encode("utf-8"), "bad": b"not-a-docx"},
    )
    result = sync_drive_source(
        clients_root=clients_root,
        client_id="tenant_a",
        source=source,
        settings=settings,
        manifest=manifest,
        drive=port,
    )
    assert result.status == "synced_with_warnings"
    assert result.files_synced == 1
    assert result.files_failed == 1
    assert "Synced with warnings" in (result.sync_summary or "")
    assert manifest.sources["docs"].status == "synced_with_warnings"


def test_missing_python_docx_produces_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins
    from pathlib import Path

    from packages.adapters.ingestion.local_upload_extractor import extract_text

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "docx":
            raise ImportError("no docx")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = extract_text(Path("sample.docx"), raw_bytes=b"fake")
    assert "pip install -r requirements.txt" in (result.reason or "")


def test_docx_extracts_when_dependency_installed() -> None:
    docx = pytest.importorskip("docx")
    from io import BytesIO

    document = docx.Document()
    document.add_paragraph(GOOD_TEXT)
    buffer = BytesIO()
    document.save(buffer)
    text, err = extract_drive_bytes(
        data=buffer.getvalue(),
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="notes.docx",
    )
    assert err is None
    assert "SimasiaAI" in (text or "")


def test_sync_summary_groups_failure_reasons() -> None:
    from packages.core.drive_sources.models import DriveFileRecord
    from packages.core.drive_sources.summary import build_sync_summary, failure_breakdown

    files = {
        "a": DriveFileRecord(
            file_id="a",
            name="a.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            status="failed_extraction",
            error="docx extraction unavailable (install python-docx)",
        )
    }
    breakdown = failure_breakdown(files)
    summary = build_sync_summary(
        status="synced_with_warnings",
        files_discovered=2,
        files_synced=1,
        files_skipped_unchanged=0,
        files_failed=1,
        failure_breakdown=breakdown,
    )
    assert "requirements.txt" in summary
    assert breakdown
