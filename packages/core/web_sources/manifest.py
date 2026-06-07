from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from packages.core.ingestion.models import utc_now_iso
from packages.core.web_sources.models import CrawlManifest, CrawlPageRecord, CrawlSourceRecord
from packages.core.web_sources.paths import crawl_manifest_path


def empty_manifest() -> CrawlManifest:
    return CrawlManifest(updated_at=None, sources={})


def load_crawl_manifest(clients_root: Path, client_id: str) -> CrawlManifest:
    path = crawl_manifest_path(clients_root, client_id)
    if not path.is_file():
        return empty_manifest()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return parse_crawl_manifest(raw)


def parse_crawl_manifest(raw: dict[str, Any]) -> CrawlManifest:
    sources: dict[str, CrawlSourceRecord] = {}
    for source_id, item in (raw.get("sources") or {}).items():
        if not isinstance(item, dict):
            continue
        pages: dict[str, CrawlPageRecord] = {}
        for page_url, page_raw in (item.get("pages") or {}).items():
            if not isinstance(page_raw, dict):
                continue
            pages[str(page_url)] = CrawlPageRecord(
                url=str(page_url),
                status=page_raw.get("status", "failed"),
                content_hash=page_raw.get("content_hash"),
                fetched_at=page_raw.get("fetched_at"),
                title=page_raw.get("title"),
                char_count=int(page_raw.get("char_count") or 0),
                error=page_raw.get("error"),
                admin_message=page_raw.get("admin_message"),
                cache_file=page_raw.get("cache_file"),
            )
        sources[str(source_id)] = CrawlSourceRecord(
            status=item.get("status", "configured"),
            last_crawled_at=item.get("last_crawled_at"),
            pages_fetched=int(item.get("pages_fetched") or 0),
            pages_failed=int(item.get("pages_failed") or 0),
            last_error=item.get("last_error"),
            admin_message=item.get("admin_message"),
            config_updated_at=item.get("config_updated_at"),
            pages=pages,
        )
    return CrawlManifest(updated_at=raw.get("updated_at"), sources=sources)


def save_crawl_manifest(clients_root: Path, client_id: str, manifest: CrawlManifest) -> None:
    path = crawl_manifest_path(clients_root, client_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest.updated_at = utc_now_iso()
    payload = {
        "updated_at": manifest.updated_at,
        "sources": {
            source_id: {
                "status": record.status,
                "last_crawled_at": record.last_crawled_at,
                "pages_fetched": record.pages_fetched,
                "pages_failed": record.pages_failed,
                "last_error": record.last_error,
                "admin_message": record.admin_message,
                "config_updated_at": record.config_updated_at,
                "pages": {
                    page_url: {
                        "url": page.url,
                        "status": page.status,
                        "content_hash": page.content_hash,
                        "fetched_at": page.fetched_at,
                        "title": page.title,
                        "char_count": page.char_count,
                        "error": page.error,
                        "admin_message": page.admin_message,
                        "cache_file": page.cache_file,
                    }
                    for page_url, page in record.pages.items()
                },
            }
            for source_id, record in manifest.sources.items()
        },
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
