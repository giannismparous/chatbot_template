from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RenderMode = Literal["static", "playwright"]
WaitUntil = Literal["networkidle", "domcontentloaded", "load"]

WebSourceRuntimeStatus = Literal[
    "configured",
    "fetched",
    "failed",
    "failed_render",
    "failed_extraction",
    "fetched_low_content",
    "blocked_by_whitelist",
    "disabled",
    "stale",
]

PageStatus = Literal[
    "fetched",
    "failed",
    "failed_render",
    "failed_extraction",
    "fetched_low_content",
    "blocked_by_robots",
    "skipped",
]

LOW_CONTENT_MIN_CHARS = 100
JS_RENDER_HINT = (
    "This page may require JS rendering; upload markdown manually or use a rendered crawler later."
)
PLAYWRIGHT_LOW_CONTENT_HINT = (
    "Rendered page had little or no readable text. Try adjusting wait_until or wait_selector."
)
PLAYWRIGHT_INSTALL_HINT = (
    "Playwright is not installed. Run: pip install playwright && playwright install chromium"
)


@dataclass
class WebSourceDefaults:
    max_depth: int = 0
    max_pages: int = 1
    crawl_delay_ms: int = 500
    respect_robots_txt: bool = True
    render_mode: RenderMode = "static"
    wait_until: WaitUntil = "networkidle"
    wait_selector: str | None = None


@dataclass
class WebSourceEntry:
    id: str
    url: str
    title: str | None = None
    enabled: bool = True
    max_depth: int = 0
    max_pages: int = 1
    respect_robots_txt: bool | None = None
    render_mode: RenderMode = "static"
    wait_until: WaitUntil = "networkidle"
    wait_selector: str | None = None


@dataclass
class WebSourcesConfig:
    version: int = 1
    updated_at: str | None = None
    defaults: WebSourceDefaults = field(default_factory=WebSourceDefaults)
    sources: list[WebSourceEntry] = field(default_factory=list)


@dataclass
class CrawlPageRecord:
    url: str
    status: PageStatus
    content_hash: str | None = None
    fetched_at: str | None = None
    title: str | None = None
    char_count: int = 0
    error: str | None = None
    admin_message: str | None = None
    cache_file: str | None = None


@dataclass
class CrawlSourceRecord:
    status: WebSourceRuntimeStatus = "configured"
    last_crawled_at: str | None = None
    pages_fetched: int = 0
    pages_failed: int = 0
    last_error: str | None = None
    admin_message: str | None = None
    config_updated_at: str | None = None
    pages: dict[str, CrawlPageRecord] = field(default_factory=dict)


@dataclass
class CrawlManifest:
    updated_at: str | None = None
    sources: dict[str, CrawlSourceRecord] = field(default_factory=dict)


@dataclass
class WebCrawlSettings:
    global_max_pages_per_source: int = 50
    global_max_depth: int = 2
    request_timeout_seconds: float = 20.0
    max_response_bytes: int = 2_000_000
    user_agent: str = "SimasiaAI-CrawlerLite/1.0 (+admin-managed)"
    deny_path_patterns: list[str] = field(default_factory=list)
    deny_query_prefixes: list[str] = field(default_factory=list)
    low_content_min_chars: int = LOW_CONTENT_MIN_CHARS
    playwright_timeout_seconds: float = 30.0
    playwright_max_timeout_seconds: float = 60.0
    playwright_enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> WebCrawlSettings:
        raw = data or {}
        web = raw.get("web_crawl") if isinstance(raw.get("web_crawl"), dict) else raw
        if not isinstance(web, dict):
            web = {}
        timeout = float(web.get("playwright_timeout_seconds", 30))
        max_timeout = float(web.get("playwright_max_timeout_seconds", 60))
        timeout = min(max(1.0, timeout), max(1.0, max_timeout))
        return cls(
            global_max_pages_per_source=int(web.get("global_max_pages_per_source", 50)),
            global_max_depth=int(web.get("global_max_depth", 2)),
            request_timeout_seconds=float(web.get("request_timeout_seconds", 20)),
            max_response_bytes=int(web.get("max_response_bytes", 2_000_000)),
            user_agent=str(web.get("user_agent") or "SimasiaAI-CrawlerLite/1.0 (+admin-managed)"),
            deny_path_patterns=[str(x) for x in (web.get("deny_path_patterns") or [])],
            deny_query_prefixes=[str(x) for x in (web.get("deny_query_prefixes") or [])],
            low_content_min_chars=int(web.get("low_content_min_chars", LOW_CONTENT_MIN_CHARS)),
            playwright_timeout_seconds=timeout,
            playwright_max_timeout_seconds=max_timeout,
            playwright_enabled=bool(web.get("playwright_enabled", True)),
        )
