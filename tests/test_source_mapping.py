from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.worker.jobs.activate_index import activate_index
from packages.config.loaders import save_yaml
from packages.core.config.loader import TenantConfigLoader
from packages.core.config.models import ConfigValidationError
from packages.core.admin.config_service import ConfigService
from packages.core.ingestion.paths import knowledge_index_path
from packages.core.ingestion.pipeline import ingest_client_uploads
from packages.core.ingestion.source_mapping import (
    SourceMappingValidationError,
    delete_mapping_entry,
    load_source_mapping,
    resolve_upload_citation,
    upsert_mapping_entry,
    validate_citation_url,
    validate_source_mapping_document,
)
from packages.core.tenant.paths import client_config_dir

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"


def _loader(clients_root: Path) -> TenantConfigLoader:
    return TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)


def _write_client(clients_root: Path, client_id: str, *, domains: list[str] | None = None) -> None:
    config_dir = clients_root / client_id / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "client.yaml").write_text(
        f"client_id: {client_id}\ndisplay_name: {client_id}\ndomain_pack: generic\n",
        encoding="utf-8",
    )
    if domains is not None:
        save_yaml(
            str(config_dir / "source_whitelist.yaml"),
            {"allowed_public_domains": domains, "citation_url_rules": {"allow_only_whitelisted": True}},
        )
    (clients_root / client_id / "uploads").mkdir(parents=True, exist_ok=True)
    (clients_root / client_id / "indexes" / "versions").mkdir(parents=True, exist_ok=True)


def test_upload_without_mapping_stays_internal(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a")
    (clients_root / "tenant_a" / "uploads" / "doc.txt").write_text("hello", encoding="utf-8")
    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="v1",
    )
    payload = json.loads(knowledge_index_path(clients_root, "tenant_a", "v1").read_text(encoding="utf-8"))
    chunk = payload["chunks"][0]
    assert chunk["internal_url"] == "uploads/doc.txt"
    assert chunk["citation_url"] is None
    assert chunk["source_visibility"] == "internal"


def test_valid_mapping_attaches_public_citation_url(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a", domains=["example.com"])
    config_dir = client_config_dir(clients_root, "tenant_a")
    upsert_mapping_entry(
        config_dir,
        rel_path="doc.txt",
        citation_url="https://example.com/doc",
        title="Doc Title",
        source_visibility="public",
        whitelist={"allowed_public_domains": ["example.com"], "citation_url_rules": {"allow_only_whitelisted": True}},
    )
    (clients_root / "tenant_a" / "uploads" / "doc.txt").write_text("hello", encoding="utf-8")
    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="v1",
    )
    chunk = json.loads(knowledge_index_path(clients_root, "tenant_a", "v1").read_text(encoding="utf-8"))["chunks"][0]
    assert chunk["citation_url"] == "https://example.com/doc"
    assert chunk["source_visibility"] == "public"
    assert chunk["title"] == "Doc Title"


def test_non_whitelisted_domain_keeps_chunk_internal(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a", domains=["client.com"])
    config_dir = client_config_dir(clients_root, "tenant_a")
    upsert_mapping_entry(
        config_dir,
        rel_path="doc.txt",
        citation_url="https://example.com/doc",
        title=None,
        source_visibility="public",
        whitelist={"allowed_public_domains": ["client.com"], "citation_url_rules": {"allow_only_whitelisted": True}},
    )
    (clients_root / "tenant_a" / "uploads" / "doc.txt").write_text("hello", encoding="utf-8")
    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="v1",
    )
    chunk = json.loads(knowledge_index_path(clients_root, "tenant_a", "v1").read_text(encoding="utf-8"))["chunks"][0]
    assert chunk["citation_url"] is None
    assert chunk["source_visibility"] == "internal"


def test_invalid_and_non_http_urls_rejected() -> None:
    with pytest.raises(SourceMappingValidationError):
        validate_citation_url("ftp://example.com/x")
    with pytest.raises(SourceMappingValidationError):
        validate_citation_url("not-a-url")
    with pytest.raises(SourceMappingValidationError):
        validate_citation_url("https://example.com/uploads/secret.pdf")


def test_title_defaults_to_filename() -> None:
    resolved = resolve_upload_citation(
        rel_path="folder/doc.txt",
        filename="doc.txt",
        entry=None,
        whitelist={},
    )
    assert resolved.title == "doc.txt"


def test_unchanged_carry_forward_reapplies_mapping(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a", domains=["example.com"])
    uploads = clients_root / "tenant_a" / "uploads"
    (uploads / "doc.txt").write_text("stable content", encoding="utf-8")
    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="v1",
    )
    activate_index(clients_root=clients_root, client_id="tenant_a")

    upsert_mapping_entry(
        client_config_dir(clients_root, "tenant_a"),
        rel_path="doc.txt",
        citation_url="https://example.com/doc",
        title="Mapped",
        source_visibility="public",
        whitelist={"allowed_public_domains": ["example.com"], "citation_url_rules": {"allow_only_whitelisted": True}},
    )
    ingest_client_uploads(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=_loader(clients_root),
        version_id="v2",
    )
    chunk = json.loads(knowledge_index_path(clients_root, "tenant_a", "v2").read_text(encoding="utf-8"))["chunks"][0]
    assert chunk["citation_url"] == "https://example.com/doc"
    assert chunk["source_visibility"] == "public"


def test_delete_mapping_entry(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    upsert_mapping_entry(
        config_dir,
        rel_path="a.txt",
        citation_url="https://example.com/a",
        title=None,
        source_visibility="public",
        whitelist={"allowed_public_domains": ["example.com"]},
    )
    assert delete_mapping_entry(config_dir, "a.txt") is True
    assert load_source_mapping(config_dir).uploads == {}


def test_bulk_config_put_validates_source_mapping(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    _write_client(clients_root, "tenant_a", domains=["example.com"])
    service = ConfigService(clients_root=clients_root)
    with pytest.raises(ConfigValidationError):
        service.put_config(
            "tenant_a",
            "source_mapping",
            {"version": 1, "uploads": {"doc.txt": {"citation_url": "ftp://bad.example/x"}}},
        )

    service.put_config(
        "tenant_a",
        "source_mapping",
        {
            "version": 1,
            "uploads": {
                "doc.txt": {
                    "citation_url": "https://example.com/doc",
                    "title": "Doc",
                    "source_visibility": "public",
                }
            },
        },
    )
    mapping = load_source_mapping(client_config_dir(clients_root, "tenant_a"))
    assert "doc.txt" in mapping.uploads
