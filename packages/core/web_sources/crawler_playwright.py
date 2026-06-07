from __future__ import annotations

from typing import Callable

from packages.core.web_sources.crawl_shared import (
    CrawlRunResult,
    FetchHtmlFn,
    HtmlFetchFailure,
    HtmlFetchSuccess,
    run_crawl_bfs,
)
from packages.core.web_sources.models import (
    PLAYWRIGHT_INSTALL_HINT,
    WebCrawlSettings,
    WebSourceEntry,
)
from packages.core.web_sources.playwright_fetch import (
    PlaywrightNotAvailableError,
    PlaywrightRenderError,
    PlaywrightTimeoutError,
    render_page_with_browser,
)

RenderFn = Callable[[str], str]


def crawl_web_source_playwright(
    *,
    clients_root,
    client_id: str,
    source: WebSourceEntry,
    settings: WebCrawlSettings,
    manifest,
    crawl_delay_ms: int = 0,
    render_fn: RenderFn | None = None,
) -> CrawlRunResult:
    if not settings.playwright_enabled:
        return _disabled_result(source.id, manifest)

    adapter, cleanup = _playwright_adapter(
        source=source,
        settings=settings,
        render_fn=render_fn,
    )
    try:
        return run_crawl_bfs(
            clients_root=clients_root,
            client_id=client_id,
            source=source,
            settings=settings,
            manifest=manifest,
            fetch_html=adapter,
            crawl_delay_ms=crawl_delay_ms,
        )
    except PlaywrightNotAvailableError as exc:
        return _failed_render_all(source, manifest, error="playwright_not_installed", admin_message=str(exc))
    finally:
        cleanup()


def _disabled_result(source_id: str, manifest) -> CrawlRunResult:
    from packages.core.ingestion.models import utc_now_iso
    from packages.core.web_sources.models import CrawlSourceRecord

    message = "Playwright crawling is disabled in ingestion config (playwright_enabled: false)."
    manifest.sources[source_id] = CrawlSourceRecord(
        status="failed_render",
        last_crawled_at=utc_now_iso(),
        last_error="playwright_disabled",
        admin_message=message,
    )
    return CrawlRunResult(
        source_id=source_id,
        status="failed_render",
        pages_fetched=0,
        pages_failed=1,
        last_error="playwright_disabled",
        admin_message=message,
    )


def _failed_render_all(source: WebSourceEntry, manifest, *, error: str, admin_message: str) -> CrawlRunResult:
    from packages.core.ingestion.models import utc_now_iso
    from packages.core.web_sources.models import CrawlPageRecord, CrawlSourceRecord

    normalized = source.url
    manifest.sources[source.id] = CrawlSourceRecord(
        status="failed_render",
        last_crawled_at=utc_now_iso(),
        pages_fetched=0,
        pages_failed=1,
        last_error=error,
        admin_message=admin_message,
        pages={
            normalized: CrawlPageRecord(
                url=normalized,
                status="failed_render",
                error=error,
                admin_message=admin_message,
            )
        },
    )
    return CrawlRunResult(
        source_id=source.id,
        status="failed_render",
        pages_fetched=0,
        pages_failed=1,
        last_error=error,
        admin_message=admin_message,
    )


def _playwright_adapter(
    *,
    source: WebSourceEntry,
    settings: WebCrawlSettings,
    render_fn: RenderFn | None,
) -> tuple[FetchHtmlFn, Callable[[], None]]:
    browser_holder: dict = {"browser": None, "playwright": None}

    def _ensure_browser():
        if browser_holder["browser"] is not None:
            return browser_holder["browser"]
        if render_fn is not None:
            browser_holder["browser"] = _MockBrowser(render_fn)
            return browser_holder["browser"]
        browser_holder["browser"], browser_holder["playwright"] = _launch_browser(settings)
        return browser_holder["browser"]

    def _cleanup() -> None:
        browser = browser_holder.get("browser")
        playwright = browser_holder.get("playwright")
        if browser is not None and playwright is not None:
            browser.close()
            playwright.stop()
        browser_holder["browser"] = None
        browser_holder["playwright"] = None

    def _fetch(url: str) -> HtmlFetchSuccess | HtmlFetchFailure:
        try:
            browser = _ensure_browser()
            html, final_url = render_page_with_browser(
                browser,
                url,
                wait_until=source.wait_until,
                wait_selector=source.wait_selector,
                timeout_seconds=settings.playwright_timeout_seconds,
                user_agent=settings.user_agent,
                render_fn=render_fn,
            )
            return HtmlFetchSuccess(html=html, final_url=final_url)
        except PlaywrightNotAvailableError:
            raise
        except PlaywrightTimeoutError:
            return HtmlFetchFailure(
                status="failed_render",
                error="playwright_timeout",
                admin_message=(
                    "Playwright could not render this page (timeout). "
                    "Check wait_until/wait_selector or increase playwright_timeout_seconds."
                ),
            )
        except PlaywrightRenderError as exc:
            return HtmlFetchFailure(
                status="failed_render",
                error="playwright_render_error",
                admin_message=str(exc),
            )
        except Exception as exc:
            return HtmlFetchFailure(
                status="failed_render",
                error="playwright_error",
                admin_message=str(exc) or PLAYWRIGHT_INSTALL_HINT,
            )

    return _fetch, _cleanup


class _MockBrowser:
    def __init__(self, render_fn: RenderFn) -> None:
        self._render_fn = render_fn

    def new_context(self, **kwargs):
        return _MockContext(self._render_fn)


class _MockContext:
    def __init__(self, render_fn: RenderFn) -> None:
        self._render_fn = render_fn

    def new_page(self):
        return _MockPage(self._render_fn)

    def close(self):
        return None


class _MockPage:
    def __init__(self, render_fn: RenderFn) -> None:
        self._render_fn = render_fn
        self.url = ""

    def goto(self, url, **kwargs):
        self.url = url

    def wait_for_selector(self, selector, **kwargs):
        return None

    def content(self):
        return self._render_fn(self.url)


def _launch_browser(settings: WebCrawlSettings):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PlaywrightNotAvailableError(PLAYWRIGHT_INSTALL_HINT) from exc

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=True)
    return browser, playwright
