from __future__ import annotations

from typing import Callable

import httpx

from packages.core.web_sources.crawl_shared import (
    CrawlRunResult,
    FetchHtmlFn,
    HtmlFetchFailure,
    HtmlFetchSuccess,
    run_crawl_bfs,
)
from packages.core.web_sources.models import WebCrawlSettings, WebSourceEntry
from packages.core.web_sources.validation import same_registrable_domain

FetchFn = Callable[[str], tuple[int, str, bytes]]


def crawl_web_source_static(
    *,
    clients_root,
    client_id: str,
    source: WebSourceEntry,
    settings: WebCrawlSettings,
    manifest,
    fetch_fn: FetchFn | None = None,
    crawl_delay_ms: int = 0,
) -> CrawlRunResult:
    fetch = fetch_fn or _default_fetch(settings)
    return run_crawl_bfs(
        clients_root=clients_root,
        client_id=client_id,
        source=source,
        settings=settings,
        manifest=manifest,
        fetch_html=_static_adapter(fetch),
        crawl_delay_ms=crawl_delay_ms,
    )


def _static_adapter(fetch: FetchFn) -> FetchHtmlFn:
    def _fetch(url: str) -> HtmlFetchSuccess | HtmlFetchFailure:
        try:
            status_code, content_type, body = fetch(url)
        except RuntimeError as exc:
            if str(exc) == "cross_domain_redirect":
                return HtmlFetchFailure(
                    status="failed",
                    error="cross_domain_redirect",
                    admin_message="Redirect left the allowed domain.",
                )
            return HtmlFetchFailure(status="failed", error=str(exc))
        except Exception as exc:
            return HtmlFetchFailure(status="failed", error=str(exc))

        if "text/html" not in content_type.lower():
            return HtmlFetchFailure(
                status="failed",
                error=f"unsupported_content_type:{content_type}",
            )
        if status_code >= 400:
            return HtmlFetchFailure(status="failed", error=f"http_{status_code}")

        html = body.decode("utf-8", errors="replace")
        return HtmlFetchSuccess(html=html, final_url=url)

    return _fetch


def _default_fetch(settings: WebCrawlSettings) -> FetchFn:
    def _fetch(url: str) -> tuple[int, str, bytes]:
        with httpx.Client(
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        ) as client:
            response = client.get(url)
            content = response.content[: settings.max_response_bytes]
            content_type = response.headers.get("content-type", "text/html")
            final_url = str(response.url)
            if not same_registrable_domain(final_url, url):
                raise RuntimeError("cross_domain_redirect")
            return response.status_code, content_type, content

    return _fetch
