from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from packages.config.loaders import save_yaml
from packages.core.citations.context_builder import build_citation_context
from packages.core.citations.enforcer import enforce_citations
from packages.core.config.loader import TenantConfigLoader
from packages.core.domain.models import RetrievedChunk
from packages.core.ingestion.pipeline import ingest_client_uploads
from packages.core.web_sources.config import add_web_source, load_web_sources
from packages.core.web_sources.crawler import crawl_web_source
from packages.core.web_sources.playwright_fetch import PlaywrightNotAvailableError
from packages.core.web_sources.models import WebCrawlSettings, WebSourceEntry
from packages.core.web_sources.service import crawl_client_web_sources
from packages.core.web_sources.validation import WebSourceValidationError, validate_public_http_url

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"

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
    save_yaml(
        str(config_dir / "web_sources.yaml"),
        {"version": 1, "defaults": {"max_depth": 0, "max_pages": 1}, "sources": []},
    )
    return clients_root


def _manifest():
    return __import__("packages.core.web_sources.manifest", fromlist=["empty_manifest"]).empty_manifest()


def test_static_mode_uses_httpx_path(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    source = WebSourceEntry(id="site", url="https://simasiaai.gr/", render_mode="static")
    settings = WebCrawlSettings.from_dict({"web_crawl": {"low_content_min_chars": 20}})
    called = {"fetch": False}

    def fetch(_url: str):
        called["fetch"] = True
        return 200, "text/html", GOOD_HTML.encode()

    with patch("packages.core.web_sources.crawler.crawl_web_source_playwright") as mock_pw:
        crawl_web_source(
            clients_root=clients_root,
            client_id="tenant_a",
            source=source,
            settings=settings,
            manifest=_manifest(),
            fetch_fn=fetch,
        )
        mock_pw.assert_not_called()
    assert called["fetch"] is True


def test_playwright_mode_dispatches_to_renderer(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    source = WebSourceEntry(
        id="site",
        url="https://simasiaai.gr/",
        render_mode="playwright",
        wait_until="networkidle",
        wait_selector="body",
    )
    settings = WebCrawlSettings.from_dict({"web_crawl": {"low_content_min_chars": 20}})
    called = {"render": False}

    def render(_url: str) -> str:
        called["render"] = True
        return GOOD_HTML

    crawl_web_source(
        clients_root=clients_root,
        client_id="tenant_a",
        source=source,
        settings=settings,
        manifest=_manifest(),
        render_fn=render,
    )
    assert called["render"] is True


def test_playwright_mock_html_writes_cache_and_ingests(tmp_path: Path) -> None:
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
        render_mode="playwright",
    )
    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    crawl_client_web_sources(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=loader,
        render_fn=lambda _url: GOOD_HTML,
    )
    cache_file = clients_root / "tenant_a" / "web_cache" / "pages" / "simasia_home" / "index.txt"
    assert cache_file.is_file()
    assert "simasiaAI" in cache_file.read_text(encoding="utf-8")

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
    web_chunks = [c for c in index["chunks"] if str(c.get("internal_url", "")).startswith("internal://web/")]
    assert web_chunks
    assert web_chunks[0]["citation_url"] == "https://simasiaai.gr/"


def test_playwright_timeout_failed_render_no_cache(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    source = WebSourceEntry(id="site", url="https://simasiaai.gr/", render_mode="playwright")
    settings = WebCrawlSettings.from_dict({"web_crawl": {"low_content_min_chars": 20}})
    manifest = _manifest()

    from packages.core.web_sources.playwright_fetch import PlaywrightTimeoutError

    def render(_url: str) -> str:
        raise PlaywrightTimeoutError("timeout")

    result = crawl_web_source(
        clients_root=clients_root,
        client_id="tenant_a",
        source=source,
        settings=settings,
        manifest=manifest,
        render_fn=render,
    )
    assert result.status == "failed_render"
    cache_dir = clients_root / "tenant_a" / "web_cache" / "pages" / "site"
    assert not list(cache_dir.glob("*.txt")) if cache_dir.exists() else True


def test_playwright_missing_failed_render_with_hint(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    source = WebSourceEntry(id="site", url="https://simasiaai.gr/", render_mode="playwright")
    settings = WebCrawlSettings.from_dict({"web_crawl": {"low_content_min_chars": 20}})
    manifest = _manifest()

    with patch(
        "packages.core.web_sources.crawler_playwright._launch_browser",
        side_effect=PlaywrightNotAvailableError("pip install playwright"),
    ):
        result = crawl_web_source(
            clients_root=clients_root,
            client_id="tenant_a",
            source=source,
            settings=settings,
            manifest=manifest,
        )
    assert result.status == "failed_render"
    assert "playwright" in (result.admin_message or "").lower()


def test_empty_rendered_dom_failed_extraction_zero_chunks(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    config_dir = clients_root / "tenant_a" / "config"
    add_web_source(
        config_dir,
        url="https://simasiaai.gr/app",
        title="App",
        enabled=True,
        max_depth=0,
        max_pages=1,
        source_id="js_site",
        whitelist={"allowed_public_domains": ["simasiaai.gr"]},
        render_mode="playwright",
    )
    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    crawl_client_web_sources(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=loader,
        render_fn=lambda _url: EMPTY_HTML,
    )
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
    web_chunks = [c for c in index["chunks"] if "internal://web/" in c.get("internal_url", "")]
    assert web_chunks == []


def test_playwright_max_pages_enforced(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    source = WebSourceEntry(
        id="site",
        url="https://simasiaai.gr/",
        render_mode="playwright",
        max_depth=1,
        max_pages=1,
    )
    settings = WebCrawlSettings.from_dict(
        {"web_crawl": {"low_content_min_chars": 20, "global_max_pages_per_source": 1}}
    )
    manifest = _manifest()

    def render(url: str) -> str:
        return LINKS_HTML if url.endswith("/") else GOOD_HTML

    result = crawl_web_source(
        clients_root=clients_root,
        client_id="tenant_a",
        source=source,
        settings=settings,
        manifest=manifest,
        render_fn=render,
    )
    assert result.pages_fetched <= 1
    assert len(manifest.sources["site"].pages) <= 1


def test_playwright_cross_domain_links_ignored(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    source = WebSourceEntry(
        id="site",
        url="https://simasiaai.gr/",
        render_mode="playwright",
        max_depth=1,
        max_pages=5,
    )
    settings = WebCrawlSettings.from_dict({"web_crawl": {"low_content_min_chars": 20}})
    manifest = _manifest()
    crawl_web_source(
        clients_root=clients_root,
        client_id="tenant_a",
        source=source,
        settings=settings,
        manifest=manifest,
        render_fn=lambda _url: LINKS_HTML,
    )
    assert not any("evil.example" in url for url in manifest.sources["site"].pages)


def test_ssrf_private_urls_still_rejected() -> None:
    with pytest.raises(WebSourceValidationError):
        validate_public_http_url("http://127.0.0.1/page")


def test_public_whitelisted_rendered_source_in_sources_when_cited() -> None:
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
    assert "web_cache" not in result.answer


def test_playwright_save_rejected_when_disabled(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    config_dir = clients_root / "tenant_a" / "config"
    with pytest.raises(WebSourceValidationError, match="playwright"):
        add_web_source(
            config_dir,
            url="https://simasiaai.gr/",
            title="Home",
            enabled=True,
            max_depth=0,
            max_pages=1,
            source_id="home",
            whitelist={"allowed_public_domains": ["simasiaai.gr"]},
            crawl_settings={"web_crawl": {"playwright_enabled": False}},
            render_mode="playwright",
        )


def test_playwright_timeout_via_service_zero_chunks(tmp_path: Path) -> None:
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
        render_mode="playwright",
    )

    from packages.core.web_sources.playwright_fetch import PlaywrightTimeoutError

    def boom(_url: str) -> str:
        raise PlaywrightTimeoutError("timeout")

    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    crawl_client_web_sources(
        clients_root=clients_root,
        client_id="tenant_a",
        config_loader=loader,
        render_fn=boom,
    )
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
    assert not [c for c in index["chunks"] if "internal://web/" in c.get("internal_url", "")]


def test_config_persists_render_mode(tmp_path: Path) -> None:
    clients_root = _seed_tenant(tmp_path)
    config_dir = clients_root / "tenant_a" / "config"
    add_web_source(
        config_dir,
        url="https://simasiaai.gr/",
        title="Home",
        enabled=True,
        max_depth=0,
        max_pages=1,
        source_id="home",
        whitelist={"allowed_public_domains": ["simasiaai.gr"]},
        render_mode="playwright",
        wait_until="domcontentloaded",
        wait_selector="main",
    )
    config = load_web_sources(config_dir)
    assert config.sources[0].render_mode == "playwright"
    assert config.sources[0].wait_until == "domcontentloaded"
    assert config.sources[0].wait_selector == "main"
