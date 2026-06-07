from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from packages.core.config.loader import TenantConfigLoader
from packages.core.ingestion.models import utc_now_iso
from packages.core.tenant.paths import client_config_dir, safe_client_id
from packages.core.web_sources.config import load_web_sources
from packages.core.web_sources.crawler import crawl_web_source
from packages.core.web_sources.manifest import load_crawl_manifest, save_crawl_manifest
from packages.core.web_sources.models import WebCrawlSettings, WebSourceRuntimeStatus
from packages.core.web_sources.paths import web_cache_pages_dir
from packages.core.web_sources.validation import domain_whitelisted


def delete_web_source_cache(clients_root: Path, client_id: str, source_id: str) -> None:
    cid = safe_client_id(client_id)
    source_dir = web_cache_pages_dir(clients_root, cid) / source_id
    if source_dir.exists():
        shutil.rmtree(source_dir, ignore_errors=True)
    manifest = load_crawl_manifest(clients_root, cid)
    manifest.sources.pop(source_id, None)
    save_crawl_manifest(clients_root, cid, manifest)


def resolve_runtime_status(
    *,
    source_enabled: bool,
    whitelisted: bool,
    crawl_record,
    config_updated_at: str | None,
) -> WebSourceRuntimeStatus:
    if not whitelisted:
        return "blocked_by_whitelist"
    if not source_enabled:
        return "disabled"
    if crawl_record is None:
        return "configured"
    if (
        config_updated_at
        and crawl_record.config_updated_at
        and config_updated_at > crawl_record.config_updated_at
    ):
        return "stale"
    return crawl_record.status or "configured"


def crawl_client_web_sources(
    *,
    clients_root: Path,
    client_id: str,
    config_loader: TenantConfigLoader,
    source_ids: list[str] | None = None,
    fetch_fn=None,
    render_fn=None,
) -> dict[str, Any]:
    cid = safe_client_id(client_id)
    config_dir = client_config_dir(clients_root, cid)
    web_config = load_web_sources(config_dir)
    merged = config_loader.load(cid)
    whitelist = merged.source_whitelist or {}
    ingestion = merged.ingestion or {}
    crawl_settings = WebCrawlSettings.from_dict(ingestion)
    manifest = load_crawl_manifest(clients_root, cid)

    selected = [
        s
        for s in web_config.sources
        if (not source_ids or s.id in source_ids)
    ]
    results = []
    for source in selected:
        if not domain_whitelisted(source.url, whitelist):
            manifest.sources[source.id] = _blocked_record(source.id)
            results.append({"source_id": source.id, "status": "blocked_by_whitelist", "skipped": True})
            continue
        if not source.enabled:
            results.append({"source_id": source.id, "status": "disabled", "skipped": True})
            continue

        result = crawl_web_source(
            clients_root=clients_root,
            client_id=cid,
            source=source,
            settings=crawl_settings,
            manifest=manifest,
            fetch_fn=fetch_fn,
            render_fn=render_fn,
            crawl_delay_ms=web_config.defaults.crawl_delay_ms,
        )
        record = manifest.sources.get(source.id)
        if record is not None:
            record.config_updated_at = web_config.updated_at
        results.append(
            {
                "source_id": result.source_id,
                "status": result.status,
                "pages_fetched": result.pages_fetched,
                "pages_failed": result.pages_failed,
                "last_error": result.last_error,
                "admin_message": result.admin_message,
            }
        )

    save_crawl_manifest(clients_root, cid, manifest)
    return {"sources": results, "updated_at": manifest.updated_at}


def _blocked_record(source_id: str):
    from packages.core.web_sources.models import CrawlSourceRecord

    return CrawlSourceRecord(
        status="blocked_by_whitelist",
        last_crawled_at=utc_now_iso(),
        last_error="Domain is not in source_whitelist allowed_public_domains.",
    )


def list_web_sources_with_status(
    *,
    clients_root: Path,
    client_id: str,
    config_loader: TenantConfigLoader,
) -> list[dict[str, Any]]:
    cid = safe_client_id(client_id)
    config_dir = client_config_dir(clients_root, cid)
    web_config = load_web_sources(config_dir)
    manifest = load_crawl_manifest(clients_root, cid)
    whitelist = config_loader.load(cid).source_whitelist or {}

    rows: list[dict[str, Any]] = []
    for source in web_config.sources:
        whitelisted = domain_whitelisted(source.url, whitelist)
        crawl_record = manifest.sources.get(source.id)
        status = resolve_runtime_status(
            source_enabled=source.enabled,
            whitelisted=whitelisted,
            crawl_record=crawl_record,
            config_updated_at=web_config.updated_at,
        )
        rows.append(
            {
                "id": source.id,
                "url": source.url,
                "title": source.title,
                "enabled": source.enabled,
                "max_depth": source.max_depth,
                "max_pages": source.max_pages,
                "render_mode": source.render_mode,
                "wait_until": source.wait_until,
                "wait_selector": source.wait_selector,
                "status": status,
                "last_crawled_at": crawl_record.last_crawled_at if crawl_record else None,
                "pages_fetched": crawl_record.pages_fetched if crawl_record else 0,
                "pages_failed": crawl_record.pages_failed if crawl_record else 0,
                "last_error": crawl_record.last_error if crawl_record else None,
                "admin_message": crawl_record.admin_message if crawl_record else None,
            }
        )
    return rows
