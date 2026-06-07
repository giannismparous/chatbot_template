from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from packages.core.drive_sources.models import (
    DriveFileRecord,
    DriveSourceDefaults,
    DriveSourceEntry,
    DriveSourceRecord,
    DriveSourcesConfig,
    DriveSyncManifest,
)
from packages.core.drive_sources.paths import drive_sync_manifest_path


def empty_manifest() -> DriveSyncManifest:
    return DriveSyncManifest(updated_at=None, sources={})


def load_drive_sync_manifest(clients_root: Path, client_id: str) -> DriveSyncManifest:
    path = drive_sync_manifest_path(clients_root, client_id)
    if not path.is_file():
        return empty_manifest()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return parse_drive_sync_manifest(raw)


def parse_drive_sync_manifest(raw: dict[str, Any]) -> DriveSyncManifest:
    sources: dict[str, DriveSourceRecord] = {}
    for source_id, item in (raw.get("sources") or {}).items():
        if not isinstance(item, dict):
            continue
        files: dict[str, DriveFileRecord] = {}
        for file_id, file_raw in (item.get("files") or {}).items():
            if not isinstance(file_raw, dict):
                continue
            files[str(file_id)] = DriveFileRecord(
                file_id=str(file_id),
                name=str(file_raw.get("name") or file_id),
                mime_type=str(file_raw.get("mime_type") or ""),
                status=file_raw.get("status", "failed_extraction"),
                modified_time=file_raw.get("modified_time"),
                content_hash=file_raw.get("content_hash"),
                cache_file=file_raw.get("cache_file"),
                web_view_link=file_raw.get("web_view_link"),
                char_count=int(file_raw.get("char_count") or 0),
                error=file_raw.get("error"),
                admin_message=file_raw.get("admin_message"),
            )
        sources[str(source_id)] = DriveSourceRecord(
            status=item.get("status", "configured"),
            last_synced_at=item.get("last_synced_at"),
            files_discovered=int(item.get("files_discovered") or 0),
            files_synced=int(item.get("files_synced") or 0),
            files_failed=int(item.get("files_failed") or 0),
            files_skipped=int(item.get("files_skipped") or 0),
            files_skipped_unchanged=int(item.get("files_skipped_unchanged") or 0),
            sync_summary=item.get("sync_summary"),
            failure_breakdown={
                str(k): int(v)
                for k, v in (item.get("failure_breakdown") or {}).items()
                if isinstance(v, (int, float, str))
            },
            last_error=item.get("last_error"),
            admin_message=item.get("admin_message"),
            config_updated_at=item.get("config_updated_at"),
            files=files,
        )
    return DriveSyncManifest(updated_at=raw.get("updated_at"), sources=sources)


def save_drive_sync_manifest(clients_root: Path, client_id: str, manifest: DriveSyncManifest) -> None:
    from packages.core.ingestion.models import utc_now_iso

    path = drive_sync_manifest_path(clients_root, client_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest.updated_at = utc_now_iso()
    payload = {
        "updated_at": manifest.updated_at,
        "sources": {
            source_id: {
                "status": record.status,
                "last_synced_at": record.last_synced_at,
                "files_discovered": record.files_discovered,
                "files_synced": record.files_synced,
                "files_failed": record.files_failed,
                "files_skipped": record.files_skipped,
                "files_skipped_unchanged": record.files_skipped_unchanged,
                "sync_summary": record.sync_summary,
                "failure_breakdown": record.failure_breakdown,
                "last_error": record.last_error,
                "admin_message": record.admin_message,
                "config_updated_at": record.config_updated_at,
                "files": {
                    file_id: {
                        "file_id": file.file_id,
                        "name": file.name,
                        "mime_type": file.mime_type,
                        "status": file.status,
                        "modified_time": file.modified_time,
                        "content_hash": file.content_hash,
                        "cache_file": file.cache_file,
                        "web_view_link": file.web_view_link,
                        "char_count": file.char_count,
                        "error": file.error,
                        "admin_message": file.admin_message,
                    }
                    for file_id, file in record.files.items()
                },
            }
            for source_id, record in manifest.sources.items()
        },
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
