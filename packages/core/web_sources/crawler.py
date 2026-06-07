from __future__ import annotations

from pathlib import Path
from typing import Callable

from packages.core.web_sources.crawl_shared import CrawlRunResult
from packages.core.web_sources.crawler_playwright import crawl_web_source_playwright
from packages.core.web_sources.crawler_static import FetchFn, crawl_web_source_static
from packages.core.web_sources.models import CrawlManifest, WebCrawlSettings, WebSourceEntry

RenderFn = Callable[[str], str]


def crawl_web_source(
    *,
    clients_root: Path,
    client_id: str,
    source: WebSourceEntry,
    settings: WebCrawlSettings,
    manifest: CrawlManifest,
    fetch_fn: FetchFn | None = None,
    render_fn: RenderFn | None = None,
    crawl_delay_ms: int = 0,
) -> CrawlRunResult:
    if source.render_mode == "playwright":
        return crawl_web_source_playwright(
            clients_root=clients_root,
            client_id=client_id,
            source=source,
            settings=settings,
            manifest=manifest,
            crawl_delay_ms=crawl_delay_ms,
            render_fn=render_fn,
        )
    return crawl_web_source_static(
        clients_root=clients_root,
        client_id=client_id,
        source=source,
        settings=settings,
        manifest=manifest,
        fetch_fn=fetch_fn,
        crawl_delay_ms=crawl_delay_ms,
    )
