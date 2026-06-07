from __future__ import annotations

from pathlib import Path
from typing import Any

from packages.config.loaders import load_yaml, save_yaml
from packages.core.ingestion.models import utc_now_iso
from packages.core.web_sources.models import (
    RenderMode,
    WaitUntil,
    WebSourceDefaults,
    WebSourceEntry,
    WebSourcesConfig,
)
from packages.core.web_sources.paths import web_sources_config_path
from packages.core.web_sources.validation import (
    WebSourceValidationError,
    clamp_depth,
    clamp_pages,
    derive_source_id_from_url,
    domain_whitelisted,
    normalize_page_url,
    validate_public_http_url,
    validate_render_mode,
    validate_source_id,
    validate_wait_selector,
    validate_wait_until,
)


def empty_web_sources() -> WebSourcesConfig:
    return WebSourcesConfig(version=1, updated_at=None, defaults=WebSourceDefaults(), sources=[])


def load_web_sources(config_dir: Path) -> WebSourcesConfig:
    path = web_sources_config_path(config_dir)
    if not path.is_file():
        return empty_web_sources()
    raw = load_yaml(str(path))
    if not isinstance(raw, dict):
        return empty_web_sources()
    return parse_web_sources_document(raw)


def parse_web_sources_document(raw: dict[str, Any]) -> WebSourcesConfig:
    defaults_raw = raw.get("defaults") or {}
    defaults = WebSourceDefaults(
        max_depth=int(defaults_raw.get("max_depth", 0)),
        max_pages=int(defaults_raw.get("max_pages", 1)),
        crawl_delay_ms=int(defaults_raw.get("crawl_delay_ms", 500)),
        respect_robots_txt=bool(defaults_raw.get("respect_robots_txt", True)),
        render_mode=validate_render_mode(defaults_raw.get("render_mode", "static")),
        wait_until=validate_wait_until(defaults_raw.get("wait_until", "networkidle")),
        wait_selector=validate_wait_selector(defaults_raw.get("wait_selector")),
    )
    sources_raw = raw.get("sources") or []
    if not isinstance(sources_raw, list):
        raise WebSourceValidationError("sources must be a list.")

    sources: list[WebSourceEntry] = []
    seen: set[str] = set()
    for item in sources_raw:
        if not isinstance(item, dict):
            raise WebSourceValidationError("Each source must be an object.")
        source_id = validate_source_id(str(item.get("id") or ""))
        if source_id in seen:
            raise WebSourceValidationError(f"Duplicate source id: {source_id}")
        seen.add(source_id)
        url = normalize_page_url(str(item.get("url") or ""))
        sources.append(
            WebSourceEntry(
                id=source_id,
                url=url,
                title=_optional_str(item.get("title")),
                enabled=bool(item.get("enabled", True)),
                max_depth=int(item.get("max_depth", defaults.max_depth)),
                max_pages=int(item.get("max_pages", defaults.max_pages)),
                respect_robots_txt=(
                    bool(item["respect_robots_txt"])
                    if item.get("respect_robots_txt") is not None
                    else None
                ),
                render_mode=validate_render_mode(item.get("render_mode", defaults.render_mode)),
                wait_until=validate_wait_until(item.get("wait_until", defaults.wait_until)),
                wait_selector=validate_wait_selector(item.get("wait_selector", defaults.wait_selector)),
            )
        )
    return WebSourcesConfig(
        version=int(raw.get("version") or 1),
        updated_at=_optional_str(raw.get("updated_at")),
        defaults=defaults,
        sources=sources,
    )


def save_web_sources(config_dir: Path, config: WebSourcesConfig) -> None:
    payload = {
        "version": config.version,
        "updated_at": config.updated_at or utc_now_iso(),
        "defaults": _defaults_payload(config.defaults),
        "sources": [_source_payload(source, config.defaults) for source in config.sources],
    }
    save_yaml(str(web_sources_config_path(config_dir)), payload)


def _defaults_payload(defaults: WebSourceDefaults) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "max_depth": defaults.max_depth,
        "max_pages": defaults.max_pages,
        "crawl_delay_ms": defaults.crawl_delay_ms,
        "respect_robots_txt": defaults.respect_robots_txt,
    }
    if defaults.render_mode != "static":
        payload["render_mode"] = defaults.render_mode
    if defaults.wait_until != "networkidle":
        payload["wait_until"] = defaults.wait_until
    if defaults.wait_selector:
        payload["wait_selector"] = defaults.wait_selector
    return payload


def _source_payload(source: WebSourceEntry, defaults: WebSourceDefaults) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": source.id,
        "url": source.url,
        "enabled": source.enabled,
        "max_depth": source.max_depth,
        "max_pages": source.max_pages,
    }
    if source.title:
        payload["title"] = source.title
    if source.respect_robots_txt is not None:
        payload["respect_robots_txt"] = source.respect_robots_txt
    if source.render_mode != defaults.render_mode:
        payload["render_mode"] = source.render_mode
    if source.wait_until != defaults.wait_until:
        payload["wait_until"] = source.wait_until
    if source.wait_selector != defaults.wait_selector and source.wait_selector:
        payload["wait_selector"] = source.wait_selector
    return payload


def apply_whitelist_policy(
    entry: WebSourceEntry,
    *,
    whitelist: dict[str, Any],
    platform_max_depth: int,
    platform_max_pages: int,
) -> WebSourceEntry:
    url = validate_public_http_url(entry.url)
    allowed = domain_whitelisted(url, whitelist)
    enabled = bool(entry.enabled) and allowed
    return WebSourceEntry(
        id=entry.id,
        url=url,
        title=entry.title,
        enabled=enabled,
        max_depth=clamp_depth(entry.max_depth, platform_max=platform_max_depth),
        max_pages=clamp_pages(entry.max_pages, platform_max=platform_max_pages),
        respect_robots_txt=entry.respect_robots_txt,
        render_mode=entry.render_mode,
        wait_until=entry.wait_until,
        wait_selector=entry.wait_selector,
    )


def add_web_source(
    config_dir: Path,
    *,
    url: str,
    title: str | None,
    enabled: bool,
    max_depth: int,
    max_pages: int,
    source_id: str | None,
    whitelist: dict[str, Any],
    crawl_settings: dict[str, Any] | None = None,
    render_mode: RenderMode = "static",
    wait_until: WaitUntil = "networkidle",
    wait_selector: str | None = None,
) -> WebSourcesConfig:
    from packages.core.web_sources.models import WebCrawlSettings

    settings = WebCrawlSettings.from_dict(crawl_settings or {})
    _validate_playwright_save(render_mode, settings)
    config = load_web_sources(config_dir)
    sid = validate_source_id(source_id or derive_source_id_from_url(url))
    if any(s.id == sid for s in config.sources):
        raise WebSourceValidationError(f"Source id already exists: {sid}")

    normalized_url = normalize_page_url(url)
    validate_public_http_url(normalized_url)
    entry = apply_whitelist_policy(
        WebSourceEntry(
            id=sid,
            url=normalized_url,
            title=_optional_str(title),
            enabled=enabled,
            max_depth=max_depth,
            max_pages=max_pages,
            render_mode=validate_render_mode(render_mode),
            wait_until=validate_wait_until(wait_until),
            wait_selector=validate_wait_selector(wait_selector),
        ),
        whitelist=whitelist,
        platform_max_depth=settings.global_max_depth,
        platform_max_pages=settings.global_max_pages_per_source,
    )
    if not domain_whitelisted(entry.url, whitelist):
        entry.enabled = False

    config.sources.append(entry)
    config.updated_at = utc_now_iso()
    save_web_sources(config_dir, config)
    return config


def _validate_playwright_save(render_mode: str, settings) -> None:
    if render_mode == "playwright" and not settings.playwright_enabled:
        raise WebSourceValidationError(
            "render_mode playwright is disabled (playwright_enabled: false in ingestion config)."
        )


def remove_web_source(config_dir: Path, source_id: str) -> WebSourcesConfig:
    sid = validate_source_id(source_id)
    config = load_web_sources(config_dir)
    config.sources = [s for s in config.sources if s.id != sid]
    config.updated_at = utc_now_iso()
    save_web_sources(config_dir, config)
    return config


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
