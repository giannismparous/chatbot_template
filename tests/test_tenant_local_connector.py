from __future__ import annotations

import json
from pathlib import Path

from apps.worker.jobs.activate_index import activate_index
from packages.adapters.connectors.tenant_local_files_connector import TenantLocalFilesConnector
from packages.core.config.loader import TenantConfigLoader
from packages.core.ingestion.pipeline import ingest_client_uploads

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"
LEGACY_KNOWLEDGE = ROOT / "packages" / "config" / "defaults" / "knowledge.json"


def _setup_client(clients_root: Path, client_id: str) -> None:
    config_dir = clients_root / client_id / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "client.yaml").write_text(
        f"client_id: {client_id}\ndisplay_name: {client_id}\ndomain_pack: generic\n",
        encoding="utf-8",
    )
    (clients_root / client_id / "uploads").mkdir(parents=True, exist_ok=True)
    (clients_root / client_id / "indexes" / "versions").mkdir(parents=True, exist_ok=True)


def test_connector_reads_active_client_index_with_chunks_shape(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _setup_client(clients_root, "tenant_a")
    (clients_root / "tenant_a" / "uploads" / "guide.txt").write_text(
        "Connector should find this unique phrase xyz123.",
        encoding="utf-8",
    )
    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=loader,
        version_id="active-read-test",
    )
    activate_index(clients_root=clients_root, client_id="tenant_a")

    connector = TenantLocalFilesConnector(
        clients_root=clients_root,
        legacy_fallback_path=str(LEGACY_KNOWLEDGE),
    )
    hits = connector.search("xyz123", limit=3, client_id="tenant_a")
    assert hits
    assert hits[0].metadata["citation_url"] is None
    assert hits[0].metadata["source_visibility"] == "internal"
    assert hits[0].metadata["internal_url"] == "uploads/guide.txt"
    assert hits[0].source == "uploads/guide.txt"


def test_connector_reads_active_client_index_with_documents_shape(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _setup_client(clients_root, "tenant_docs")
    indexes = clients_root / "tenant_docs" / "indexes"
    version_id = "docs-shape-v1"
    version_dir = indexes / "versions" / version_id
    version_dir.mkdir(parents=True)
    (version_dir / "knowledge_index.json").write_text(
        json.dumps(
            {
                "client_id": "tenant_docs",
                "version_id": version_id,
                "documents": [
                    {
                        "id": "doc-legacy-1",
                        "title": "Legacy Document",
                        "content": "documents shape marker docshape42",
                        "url": "internal://legacy-doc",
                        "language": "en",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (version_dir / "source_manifest.json").write_text("{}", encoding="utf-8")
    (indexes / "active_manifest.json").write_text(
        json.dumps({"active": version_id}),
        encoding="utf-8",
    )

    connector = TenantLocalFilesConnector(
        clients_root=clients_root,
        legacy_fallback_path=str(LEGACY_KNOWLEDGE),
    )
    hits = connector.search("docshape42", limit=3, client_id="tenant_docs")
    assert hits
    assert hits[0].id == "doc-legacy-1"
    assert hits[0].metadata["internal_url"] == "internal://legacy-doc"


def test_connector_falls_back_to_legacy_without_active_index(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _setup_client(clients_root, "unmigrated")

    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        json.dumps(
            [
                {
                    "id": "legacy-1",
                    "title": "Legacy Doc",
                    "content": "legacy fallback marker abc999",
                    "url": "internal://legacy",
                    "language": "en",
                }
            ]
        ),
        encoding="utf-8",
    )

    connector = TenantLocalFilesConnector(
        clients_root=clients_root,
        legacy_fallback_path=str(legacy),
    )
    hits = connector.search("abc999", limit=3, client_id="unmigrated")
    assert hits
    assert hits[0].id == "legacy-1"


def test_connector_rejects_invalid_client_id(tmp_path: Path) -> None:
    connector = TenantLocalFilesConnector(
        clients_root=tmp_path / "clients",
        legacy_fallback_path=str(LEGACY_KNOWLEDGE),
    )
    assert connector.search("anything", client_id="../bad") == []
