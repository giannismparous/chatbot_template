from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest

from apps.worker.jobs.activate_index import activate_index
from packages.core.config.loader import TenantConfigLoader
from packages.core.ingestion.manifest import read_active_manifest
from packages.core.ingestion.nfc import normalize_filename_nfc, normalize_text_nfc
from packages.core.ingestion.paths import (
    active_manifest_path,
    knowledge_index_path,
    source_manifest_path,
)
from packages.core.ingestion.pipeline import ingest_client_uploads, should_skip_file
from packages.core.tenant.paths import safe_client_id

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"
LEGACY_KNOWLEDGE = ROOT / "packages" / "config" / "defaults" / "knowledge.json"


def _loader(clients_root: Path) -> TenantConfigLoader:
    return TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)


def _write_client(clients_root: Path, client_id: str) -> None:
    config_dir = clients_root / client_id / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "client.yaml").write_text(
        f"client_id: {client_id}\ndisplay_name: {client_id}\ndomain_pack: generic\n",
        encoding="utf-8",
    )
    (clients_root / client_id / "uploads").mkdir(parents=True, exist_ok=True)
    (clients_root / client_id / "indexes" / "versions").mkdir(parents=True, exist_ok=True)


def test_ingest_txt_creates_pending_version(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a")
    uploads = clients_root / "tenant_a" / "uploads"
    (uploads / "notes.txt").write_text("Tenant A knowledge about widgets.", encoding="utf-8")

    result = ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="v-pending-001",
    )

    assert result.version_id == "v-pending-001"
    assert result.chunk_count >= 1
    assert result.indexed_count == 1

    manifest = read_active_manifest(active_manifest_path(clients_root, "tenant_a"))
    assert manifest.pending == "v-pending-001"
    assert manifest.active is None

    index_path = knowledge_index_path(clients_root, "tenant_a", "v-pending-001")
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    chunk = payload["chunks"][0]
    assert chunk["internal_url"] == "uploads/notes.txt"
    assert chunk["citation_url"] is None
    assert chunk["source_visibility"] == "internal"


def test_activate_switches_active_and_preserves_previous(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a")
    uploads = clients_root / "tenant_a" / "uploads"

    (uploads / "v1.txt").write_text("version one content", encoding="utf-8")
    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="version-one",
    )
    activate_index(clients_root=clients_root, client_id="tenant_a")

    (uploads / "v2.txt").write_text("version two content", encoding="utf-8")
    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="version-two",
    )
    activate_index(clients_root=clients_root, client_id="tenant_a")

    manifest = read_active_manifest(active_manifest_path(clients_root, "tenant_a"))
    assert manifest.active == "version-two"
    assert manifest.previous == "version-one"
    assert manifest.pending is None
    assert knowledge_index_path(clients_root, "tenant_a", "version-one").is_file()
    assert knowledge_index_path(clients_root, "tenant_a", "version-two").is_file()


def test_tenant_indexes_are_isolated(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    for cid, text in (("tenant_a", "alpha secret phrase"), ("tenant_b", "beta secret phrase")):
        _write_client(clients_root, cid)
        (clients_root / cid / "uploads" / "doc.txt").write_text(text, encoding="utf-8")
        ingest_client_uploads(
            clients_root=clients_root,
            client_id=cid,
            config_loader=_loader(clients_root),
            version_id=f"{cid}-v1",
        )
        activate_index(clients_root=clients_root, client_id=cid)

    from packages.adapters.connectors.tenant_local_files_connector import TenantLocalFilesConnector

    connector = TenantLocalFilesConnector(
        clients_root=clients_root,
        legacy_fallback_path=str(LEGACY_KNOWLEDGE),
    )
    a_hits = connector.search("alpha secret", limit=5, client_id="tenant_a")
    b_hits = connector.search("beta secret", limit=5, client_id="tenant_b")

    assert any("alpha" in h.text.lower() for h in a_hits)
    assert not any("beta" in h.text.lower() for h in a_hits)
    assert any("beta" in h.text.lower() for h in b_hits)
    assert not any("alpha" in h.text.lower() for h in b_hits)


def test_skip_files_prevents_indexing(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a")
    config_dir = clients_root / "tenant_a" / "config"
    (config_dir / "ingestion.yaml").write_text(
        "skip_files:\n  - 'secret.txt'\n",
        encoding="utf-8",
    )
    uploads = clients_root / "tenant_a" / "uploads"
    (uploads / "secret.txt").write_text("must not index", encoding="utf-8")
    (uploads / "public.txt").write_text("safe to index", encoding="utf-8")

    result = ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="skip-test",
    )

    assert result.indexed_count == 1
    assert result.skipped_count == 1
    sources = json.loads(
        source_manifest_path(clients_root, "tenant_a", "skip-test").read_text(encoding="utf-8")
    )["sources"]
    by_name = {s["filename"]: s for s in sources}
    assert by_name["secret.txt"]["status"] == "skipped"
    assert by_name["public.txt"]["status"] == "indexed"


def test_unsupported_file_recorded_without_crash(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a")
    uploads = clients_root / "tenant_a" / "uploads"
    (uploads / "data.bin").write_bytes(b"\x00\x01\x02")
    (uploads / "ok.txt").write_text("still works", encoding="utf-8")

    result = ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="unsupported-test",
    )

    assert result.unsupported_count == 1
    assert result.indexed_count == 1
    sources = json.loads(
        source_manifest_path(clients_root, "tenant_a", "unsupported-test").read_text(encoding="utf-8")
    )["sources"]
    bin_record = next(s for s in sources if s["filename"] == "data.bin")
    assert bin_record["status"] == "unsupported"
    assert bin_record["reason"]


def test_nfc_filename_and_text_normalization(tmp_path: Path) -> None:
    nfd_name = "cafe\u0301.txt"
    nfc_name = normalize_filename_nfc(nfd_name)
    assert nfc_name == "caf\u00e9.txt"
    assert unicodedata.normalize("NFC", nfd_name) == nfc_name

    nfd_text = "e\u0301"
    assert normalize_text_nfc(nfd_text) == "\u00e9"
    assert unicodedata.is_normalized("NFC", normalize_text_nfc(nfd_text))

    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a")
    uploads = clients_root / "tenant_a" / "uploads"
    (uploads / nfd_name).write_text("NFC body e\u0301", encoding="utf-8")

    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="nfc-test",
    )
    sources = json.loads(
        source_manifest_path(clients_root, "tenant_a", "nfc-test").read_text(encoding="utf-8")
    )["sources"]
    assert sources[0]["filename"] == nfc_name


def test_should_skip_file_glob() -> None:
    assert should_skip_file("draft.tmp", ["*.tmp"])
    assert not should_skip_file("notes.txt", ["*.tmp"])


def test_path_traversal_client_id_rejected() -> None:
    with pytest.raises(ValueError):
        safe_client_id("../tenant_a")
    with pytest.raises(ValueError):
        ingest_client_uploads(
            clients_root=Path("/tmp/clients"),
            client_id="../evil",
            config_loader=_loader(Path("/tmp/clients")),
        )
