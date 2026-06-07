from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packages.config.loaders import save_yaml
from packages.core.config.loader import TenantConfigLoader
from packages.core.ingestion.pipeline import ingest_client_uploads
from packages.core.orchestrator.chat_orchestrator import ChatOrchestrator
from packages.core.domain.models import ChatRequest, RetrievedChunk
from packages.core.retrieval.models import RetrievalOutcome
from packages.core.web_sources.config import add_web_source, load_web_sources
from packages.core.web_sources.crawler import crawl_web_source
from packages.core.web_sources.extractor import extract_readable_text
from packages.core.web_sources.link_filter import should_skip_url
from packages.core.web_sources.manifest import load_crawl_manifest
from packages.core.web_sources.models import WebCrawlSettings, WebSourceEntry
from packages.core.web_sources.robots import RobotsChecker
from packages.core.web_sources.service import crawl_client_web_sources
from packages.core.web_sources.validation import (
    WebSourceValidationError,
    normalize_page_url,
    same_registrable_domain,
    validate_public_http_url,
)
from packages.core.citations.enforcer import enforce_citations
from packages.core.citations.context_builder import build_citation_context

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"
ADMIN_HEADERS = {"x-admin-token": "test-admin-token"}


GOOD_HTML = """
<html><head><title>Simasia Home</title></head><body>
<main><h1>simasiaAI</h1>
<p>We build Greek chatbots for regulated domains with source-backed answers and safety guardrails.</p>
<p>Every answer links to the original public page so users can verify claims quickly.</p>
</main></body></html>
"""

LINKS_HTML = """
<html><body><main>
<p>Seed page with enough readable text for crawler-lite extraction in regulated domains and public websites.</p>
<p>Additional paragraph so extraction exceeds the low-content threshold for ingestion.</p>
<a href="/collaborations">Collaborations</a>
<a href="https://evil.example/other">External</a>
<a href="/style.css">Style</a>
<a href="/admin/login">Admin</a>
</main></body></html>
"""

EMPTY_HTML = "<html><head></head><body><div id='app'></div></body></html>"


def _seed_tenant(tmp_path: Path, *, domains: list[str] | None = None) -> Path:
    clients_root = tmp_path / "clients"
    config_dir = clients_root / "tenant_a" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (clients_root / "tenant_a" / "uploads").mkdir(parents=True, exist_ok=True)
    (clients_root / "tenant_a" / "web_cache").mkdir(parents=True, exist_ok=True)
    (clients_root / "tenant_a" / "indexes" / "versions").mkdir(parents=True, exist_ok=True)
    save_yaml(
        str(config_dir / "client.yaml"),
        {"client_id": "tenant_a", "display_name": "Tenant A", "domain_pack": "generic"},
    )
    save_yaml(
        str(config_dir / "source_whitelist.yaml"),
        {"allowed_public_domains": domains or ["simasiaai.gr"]},
    )
    save_yaml(str(config_dir / "web_sources.yaml"), {"version": 1, "defaults": {"max_depth": 0, "max_pages": 1}, "sources": []})
    return clients_root


def test_valid_url_saves(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    config_dir = clients_root / "tenant_a" / "config"
    add_web_source(
        config_dir,
        url="https://simasiaai.gr/",
        title="Home",
        enabled=True,
        max_depth=0,
        max_pages=1,
        source_id="simasia_home",
        whitelist={"allowed_public_domains": ["simasiaai.gr"]},
    )
    config = load_web_sources(config_dir)
    assert len(config.sources) == 1
    assert config.sources[0].url == "https://simasiaai.gr/"


def test_invalid_non_http_rejected() -> None:
    with pytest.raises(WebSourceValidationError):
        validate_public_http_url("ftp://simasiaai.gr/")


def test_localhost_private_ip_rejected() -> None:
    with pytest.raises(WebSourceValidationError):
        validate_public_http_url("http://127.0.0.1/page")
    with pytest.raises(WebSourceValidationError):
        validate_public_http_url("http://192.168.1.10/page")


def test_non_whitelisted_saved_disabled(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path, domains=["simasiaai.gr"])
    config_dir = clients_root / "tenant_a" / "config"
    add_web_source(
        config_dir,
        url="https://other.example/page",
        title="Other",
        enabled=True,
        max_depth=0,
        max_pages=1,
        source_id="other_site",
        whitelist={"allowed_public_domains": ["simasiaai.gr"]},
    )
    config = load_web_sources(config_dir)
    assert config.sources[0].enabled is False


def test_non_whitelisted_not_crawled(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path, domains=["simasiaai.gr"])
    config_dir = clients_root / "tenant_a" / "config"
    add_web_source(
        config_dir,
        url="https://other.example/page",
        title="Other",
        enabled=True,
        max_depth=0,
        max_pages=1,
        source_id="other_site",
        whitelist={"allowed_public_domains": ["simasiaai.gr"]},
    )
    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    result = crawl_client_web_sources(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=loader,
        fetch_fn=lambda _url: (200, "text/html", GOOD_HTML.encode()),
    )
    assert result["sources"][0]["skipped"] is True


def test_same_domain_only_and_limits(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    source = WebSourceEntry(
        id="site",
        url="https://simasiaai.gr/",
        title="Home",
        enabled=True,
        max_depth=1,
        max_pages=2,
    )
    settings = WebCrawlSettings.from_dict(
        {
            "web_crawl": {
                "deny_path_patterns": ["/admin"],
                "deny_query_prefixes": ["utm_"],
                "low_content_min_chars": 20,
            }
        }
    )

    def fetch(url: str):
        if url.endswith("/"):
            return 200, "text/html", LINKS_HTML.encode()
        if url.endswith("/collaborations"):
            return 200, "text/html", GOOD_HTML.encode()
        raise AssertionError(f"unexpected fetch {url}")

    manifest = __import__("packages.core.web_sources.manifest", fromlist=["empty_manifest"]).empty_manifest()
    result = crawl_web_source(
        clients_root=clients_root,
        client_id="tenant_a",
        source=source,
        settings=settings,
        manifest=manifest,
        fetch_fn=fetch,
    )
    assert result.pages_fetched <= 2
    assert not any("evil.example" in url for url in manifest.sources["site"].pages)
    assert not any("/admin" in url for url in manifest.sources["site"].pages)


def test_asset_admin_query_links_skipped() -> None:
    settings = WebCrawlSettings.from_dict({"web_crawl": {"deny_path_patterns": ["/admin"], "deny_query_prefixes": ["utm_"]}})
    assert should_skip_url("https://simasiaai.gr/style.css", deny_path_patterns=settings.deny_path_patterns, deny_query_prefixes=settings.deny_query_prefixes)
    assert should_skip_url("https://simasiaai.gr/admin/login", deny_path_patterns=settings.deny_path_patterns, deny_query_prefixes=settings.deny_query_prefixes)
    assert should_skip_url("https://simasiaai.gr/page?utm_source=x", deny_path_patterns=settings.deny_path_patterns, deny_query_prefixes=settings.deny_query_prefixes)


def test_cross_domain_links_ignored() -> None:
    assert not same_registrable_domain("https://simasiaai.gr/", "https://evil.example/page")


def test_empty_extraction_status(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    source = WebSourceEntry(id="js_site", url="https://simasiaai.gr/app", enabled=True, max_depth=0, max_pages=1)
    settings = WebCrawlSettings.from_dict({"web_crawl": {"low_content_min_chars": 100}})
    manifest = __import__("packages.core.web_sources.manifest", fromlist=["empty_manifest"]).empty_manifest()
    result = crawl_web_source(
        clients_root=clients_root,
        client_id="tenant_a",
        source=source,
        settings=settings,
        manifest=manifest,
        fetch_fn=lambda _url: (200, "text/html", EMPTY_HTML.encode()),
    )
    assert result.status in {"failed_extraction", "failed"}
    assert result.admin_message


def test_failed_extraction_pages_not_ingested(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    config_dir = clients_root / "tenant_a" / "config"
    add_web_source(
        config_dir,
        url="https://simasiaai.gr/",
        title="JS Home",
        enabled=True,
        max_depth=0,
        max_pages=1,
        source_id="simasia_home",
        whitelist={"allowed_public_domains": ["simasiaai.gr"]},
    )
    (clients_root / "tenant_a" / "uploads" / "manual.md").write_text(
        "Uploaded manual fallback content for simasiaAI with enough text to index.",
        encoding="utf-8",
    )
    manifest_path = clients_root / "tenant_a" / "web_cache" / "crawl_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "sources": {
                    "simasia_home": {
                        "status": "failed_extraction",
                        "pages": {
                            "https://simasiaai.gr/": {
                                "url": "https://simasiaai.gr/",
                                "status": "failed_extraction",
                                "error": "empty_extraction",
                                "admin_message": "This page may require JS rendering",
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
        (clients_root / "tenant_a" / "indexes" / "versions" / result.version_id / "knowledge_index.json").read_text(
            encoding="utf-8"
        )
    )
    web_chunks = [c for c in index["chunks"] if str(c.get("internal_url", "")).startswith("internal://web/")]
    upload_chunks = [c for c in index["chunks"] if str(c.get("internal_url", "")).startswith("uploads/")]
    assert web_chunks == []
    assert upload_chunks
    assert all(c.get("content") for c in index["chunks"])


def test_robots_disallow_blocks_page() -> None:
    checker = RobotsChecker(user_agent="test-bot")
    checker._parsers["https://simasiaai.gr"] = type("_P", (), {"can_fetch": lambda _s, _a, _u: False})()
    allowed, reason = checker.can_fetch("https://simasiaai.gr/private")
    assert allowed is False
    assert reason == "blocked_by_robots"


def test_crawled_page_ingested_with_public_citation(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    config_dir = clients_root / "tenant_a" / "config"
    add_web_source(
        config_dir,
        url="https://simasiaai.gr/",
        title="Home",
        enabled=True,
        max_depth=0,
        max_pages=1,
        source_id="simasia_home",
        whitelist={"allowed_public_domains": ["simasiaai.gr"]},
    )
    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    crawl_client_web_sources(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=loader,
        fetch_fn=lambda _url: (200, "text/html", GOOD_HTML.encode()),
    )
    result = ingest_client_uploads(clients_root=clients_root, client_id="tenant_a", config_loader=loader)
    index = json.loads(
        (clients_root / "tenant_a" / "indexes" / "versions" / result.version_id / "knowledge_index.json").read_text(
            encoding="utf-8"
        )
    )
    web_chunks = [c for c in index["chunks"] if str(c.get("internal_url", "")).startswith("internal://web/")]
    assert web_chunks
    assert web_chunks[0]["citation_url"] == "https://simasiaai.gr/"
    assert web_chunks[0]["source_visibility"] == "public"
    blob = json.dumps(index)
    assert "web_cache" not in blob


def test_non_whitelisted_web_sources_not_ingested(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path, domains=["simasiaai.gr"])
    config_dir = clients_root / "tenant_a" / "config"
    save_yaml(
        str(config_dir / "web_sources.yaml"),
        {
            "version": 1,
            "sources": [
                {
                    "id": "other",
                    "url": "https://other.example/",
                    "enabled": True,
                    "max_depth": 0,
                    "max_pages": 1,
                }
            ],
        },
    )
    pages_dir = clients_root / "tenant_a" / "web_cache" / "pages" / "other"
    pages_dir.mkdir(parents=True, exist_ok=True)
    (pages_dir / "index.txt").write_text("Other site content with enough text for ingestion.", encoding="utf-8")
    manifest_path = clients_root / "tenant_a" / "web_cache" / "crawl_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "sources": {
                    "other": {
                        "status": "fetched",
                        "pages": {
                            "https://other.example/": {
                                "url": "https://other.example/",
                                "status": "fetched",
                                "content_hash": "abc",
                                "cache_file": "index.txt",
                                "title": "Other",
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
        (clients_root / "tenant_a" / "indexes" / "versions" / result.version_id / "knowledge_index.json").read_text(
            encoding="utf-8"
        )
    )
    web_chunks = [c for c in index["chunks"] if "internal://web/" in c.get("internal_url", "")]
    assert web_chunks == []


def test_resolve_web_citation_non_whitelisted_is_internal() -> None:
    from packages.core.web_sources.citation import resolve_web_citation

    resolved = resolve_web_citation(
        page_url="https://other.example/page",
        title="Other",
        whitelist={"allowed_public_domains": ["simasiaai.gr"]},
    )
    assert resolved.source_visibility == "internal"
    assert resolved.citation_url is None


def test_public_web_source_in_sources_when_cited() -> None:
    chunk = RetrievedChunk(
        id="web1",
        text="Simasia content",
        source="internal://web/simasia_home/index",
        score=0.9,
        metadata={
            "title": "Home",
            "internal_url": "internal://web/simasia_home/index",
            "citation_url": "https://simasiaai.gr/",
            "source_visibility": "public",
        },
    )
    ctx = build_citation_context([chunk])
    whitelist = {"allowed_public_domains": ["simasiaai.gr"], "citation_url_rules": {"allow_only_whitelisted": True}}
    result = enforce_citations("Answer [1].", ctx, whitelist)
    assert result.public_sources[0].url == "https://simasiaai.gr/"
    assert "internal://web" not in result.answer


def test_admin_web_sources_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        "/v1/admin/clients/tenant_a/web-sources",
        headers=ADMIN_HEADERS,
        json={"url": "https://simasiaai.gr/", "title": "Home", "enabled": True, "max_depth": 0, "max_pages": 1, "id": "home"},
    )
    assert res.status_code == 201
    listed = client.get("/v1/admin/clients/tenant_a/web-sources", headers=ADMIN_HEADERS)
    assert listed.status_code == 200
    assert listed.json()["sources"][0]["status"] in {"configured", "blocked_by_whitelist", "disabled"}
    delete = client.delete("/v1/admin/clients/tenant_a/web-sources/home", headers=ADMIN_HEADERS)
    assert delete.status_code == 204
    stack_module.reset_stack()
