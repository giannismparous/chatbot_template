from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import urljoin, urlparse

from packages.core.ingestion.models import utc_now_iso
from packages.core.ingestion.nfc import normalize_text_nfc
from packages.core.web_sources.citation import low_content_message
from packages.core.web_sources.extractor import extract_page_title, extract_readable_text
from packages.core.web_sources.link_filter import should_skip_url
from packages.core.web_sources.models import (
    CrawlManifest,
    CrawlPageRecord,
    CrawlSourceRecord,
    WebCrawlSettings,
    WebSourceEntry,
)
from packages.core.web_sources.paths import web_cache_pages_dir
from packages.core.web_sources.robots import RobotsChecker
from packages.core.web_sources.validation import normalize_page_url, same_registrable_domain

FetchHtmlFn = Callable[[str], "HtmlFetchOutcome"]


@dataclass
class CrawlRunResult:
    source_id: str
    status: str
    pages_fetched: int
    pages_failed: int
    last_error: str | None = None
    admin_message: str | None = None


@dataclass
class HtmlFetchSuccess:
    html: str
    final_url: str


@dataclass
class HtmlFetchFailure:
    status: Literal["failed", "failed_render"]
    error: str
    admin_message: str | None = None


HtmlFetchOutcome = HtmlFetchSuccess | HtmlFetchFailure


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def page_key(url: str, *, seed_url: str) -> str:
    if normalize_page_url(url) == normalize_page_url(seed_url):
        return "index"
    parsed = urlparse(url)
    slug = (parsed.path.strip("/") or "index").replace("/", "_")
    return slug[:120] or "index"


def extract_links(html: str, base_url: str, *, seed_url: str) -> list[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        absolute = urljoin(base_url, href)
        try:
            normalized = normalize_page_url(absolute)
        except Exception:
            continue
        if not same_registrable_domain(normalized, seed_url):
            continue
        found.append(normalized)
    return found


def process_html_page(
    *,
    html: str,
    normalized: str,
    source: WebSourceEntry,
    settings: WebCrawlSettings,
    pages_dir: Path,
    seed_url: str,
) -> tuple[CrawlPageRecord, bool]:
    text = normalize_text_nfc(extract_readable_text(html))
    title = extract_page_title(html) or source.title or normalized
    char_count = len(text)
    key = page_key(normalized, seed_url=seed_url)
    playwright = source.render_mode == "playwright"

    if char_count <= 0:
        return (
            CrawlPageRecord(
                url=normalized,
                status="failed_extraction",
                title=title,
                char_count=0,
                error="empty_extraction",
                admin_message=low_content_message(
                    0,
                    min_chars=settings.low_content_min_chars,
                    playwright=playwright,
                ),
            ),
            False,
        )
    if char_count < settings.low_content_min_chars:
        return (
            CrawlPageRecord(
                url=normalized,
                status="fetched_low_content",
                title=title,
                char_count=char_count,
                admin_message=low_content_message(
                    char_count,
                    min_chars=settings.low_content_min_chars,
                    playwright=playwright,
                ),
            ),
            False,
        )

    text_path = pages_dir / f"{key}.txt"
    text_path.write_text(text, encoding="utf-8")
    return (
        CrawlPageRecord(
            url=normalized,
            status="fetched",
            content_hash=content_hash(text),
            fetched_at=utc_now_iso(),
            title=title,
            char_count=char_count,
            cache_file=f"{key}.txt",
        ),
        True,
    )


def compute_source_status(*, pages: dict[str, CrawlPageRecord], fetched_count: int, failed_count: int) -> str:
    if fetched_count > 0:
        return "fetched"
    if any(p.status == "failed_render" for p in pages.values()):
        return "failed_render"
    if any(p.status == "failed_extraction" for p in pages.values()):
        return "failed_extraction"
    if any(p.status == "fetched_low_content" for p in pages.values()):
        return "fetched_low_content"
    if failed_count > 0:
        return "failed"
    return "failed"


def run_crawl_bfs(
    *,
    clients_root: Path,
    client_id: str,
    source: WebSourceEntry,
    settings: WebCrawlSettings,
    manifest: CrawlManifest,
    fetch_html: FetchHtmlFn,
    crawl_delay_ms: int = 0,
) -> CrawlRunResult:
    pages_dir = web_cache_pages_dir(clients_root, client_id) / source.id
    pages_dir.mkdir(parents=True, exist_ok=True)

    seed_url = source.url
    max_depth = min(source.max_depth, settings.global_max_depth)
    max_pages = min(source.max_pages, settings.global_max_pages_per_source)
    respect_robots = (
        source.respect_robots_txt if source.respect_robots_txt is not None else True
    )
    robots = RobotsChecker(user_agent=settings.user_agent)
    delay_seconds = max(0.0, crawl_delay_ms / 1000.0)

    queue: list[tuple[str, int]] = [(seed_url, 0)]
    seen: set[str] = set()
    pages: dict[str, CrawlPageRecord] = {}
    fetched_count = 0
    failed_count = 0
    last_error: str | None = None
    admin_message: str | None = None
    last_fetch_at = 0.0

    while queue and len(pages) < max_pages:
        url, depth = queue.pop(0)
        normalized = normalize_page_url(url)
        if normalized in seen:
            continue
        seen.add(normalized)

        if should_skip_url(
            normalized,
            deny_path_patterns=settings.deny_path_patterns,
            deny_query_prefixes=settings.deny_query_prefixes,
        ):
            pages[normalized] = CrawlPageRecord(
                url=normalized,
                status="skipped",
                error="denied_by_policy",
            )
            continue

        if respect_robots:
            allowed, reason = robots.can_fetch(normalized)
            if not allowed:
                pages[normalized] = CrawlPageRecord(
                    url=normalized,
                    status="blocked_by_robots",
                    error=reason,
                )
                failed_count += 1
                continue

        if last_fetch_at and delay_seconds > 0:
            elapsed = time.time() - last_fetch_at
            if elapsed < delay_seconds:
                time.sleep(delay_seconds - elapsed)

        outcome = fetch_html(normalized)
        last_fetch_at = time.time()

        if isinstance(outcome, HtmlFetchFailure):
            pages[normalized] = CrawlPageRecord(
                url=normalized,
                status=outcome.status,
                error=outcome.error,
                admin_message=outcome.admin_message,
            )
            failed_count += 1
            last_error = outcome.error
            if outcome.admin_message:
                admin_message = outcome.admin_message
            continue

        if not same_registrable_domain(outcome.final_url, seed_url):
            pages[normalized] = CrawlPageRecord(
                url=normalized,
                status="failed_render",
                error="cross_domain_redirect",
                admin_message="Navigation left the allowed domain.",
            )
            failed_count += 1
            last_error = "cross_domain_redirect"
            continue

        record, is_fetched = process_html_page(
            html=outcome.html,
            normalized=normalized,
            source=source,
            settings=settings,
            pages_dir=pages_dir,
            seed_url=seed_url,
        )
        pages[normalized] = record
        if is_fetched:
            fetched_count += 1
        else:
            failed_count += 1
            last_error = record.error or record.status
            if record.admin_message:
                admin_message = record.admin_message

        if depth < max_depth and len(pages) < max_pages:
            for link in extract_links(outcome.html, normalized, seed_url=seed_url):
                if link not in seen:
                    queue.append((link, depth + 1))

    source_status = compute_source_status(
        pages=pages,
        fetched_count=fetched_count,
        failed_count=failed_count,
    )

    manifest.sources[source.id] = CrawlSourceRecord(
        status=source_status,
        last_crawled_at=utc_now_iso(),
        pages_fetched=fetched_count,
        pages_failed=failed_count,
        last_error=last_error,
        admin_message=admin_message,
        pages=pages,
    )
    return CrawlRunResult(
        source_id=source.id,
        status=source_status,
        pages_fetched=fetched_count,
        pages_failed=failed_count,
        last_error=last_error,
        admin_message=admin_message,
    )
