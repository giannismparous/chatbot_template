from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from packages.core.config.loader import TenantConfigLoader
from packages.core.drive_sources.config import load_drive_sources, remove_drive_source
from packages.core.drive_sources.credentials import build_drive_service, load_drive_credentials_info
from packages.core.drive_sources.manifest import load_drive_sync_manifest, save_drive_sync_manifest
from packages.core.drive_sources.models import DriveSourceRuntimeStatus, DriveSyncSettings
from packages.core.drive_sources.paths import drive_cache_files_dir
from packages.core.drive_sources.sync import GoogleDriveApiPort, sync_drive_source
from packages.core.tenant.paths import client_config_dir, safe_client_id


def delete_drive_source_cache(clients_root: Path, client_id: str, source_id: str) -> None:
    cid = safe_client_id(client_id)
    source_dir = drive_cache_files_dir(clients_root, cid) / source_id
    if source_dir.exists():
        shutil.rmtree(source_dir, ignore_errors=True)
    manifest = load_drive_sync_manifest(clients_root, cid)
    manifest.sources.pop(source_id, None)
    save_drive_sync_manifest(clients_root, cid, manifest)


def resolve_runtime_status(
    *,
    source_enabled: bool,
    sync_record,
    config_updated_at: str | None,
) -> DriveSourceRuntimeStatus:
    if not source_enabled:
        return "disabled"
    if sync_record is None:
        return "configured"
    if (
        config_updated_at
        and sync_record.config_updated_at
        and config_updated_at > sync_record.config_updated_at
    ):
        return "stale"
    return sync_record.status or "configured"


def sync_client_drive_sources(
    *,
    clients_root: Path,
    client_id: str,
    config_loader: TenantConfigLoader,
    source_ids: list[str] | None = None,
    drive_port=None,
) -> dict[str, Any]:
    cid = safe_client_id(client_id)
    config_dir = client_config_dir(clients_root, cid)
    drive_config = load_drive_sources(config_dir)
    merged = config_loader.load(cid)
    sync_settings = DriveSyncSettings.from_dict(merged.ingestion)
    manifest = load_drive_sync_manifest(clients_root, cid)

    creds = load_drive_credentials_info()
    if drive_port is None:
        if not creds.configured:
            for source in drive_config.sources:
                if source_ids and source.id not in source_ids:
                    continue
                manifest.sources[source.id] = _missing_credentials_record(creds.error or "missing credentials")
            save_drive_sync_manifest(clients_root, cid, manifest)
            return {
                "sources": [
                    {"source_id": s.id, "status": "failed_auth", "skipped": False, "admin_message": creds.error}
                    for s in drive_config.sources
                    if not source_ids or s.id in source_ids
                ],
                "credentials_configured": False,
                "service_account_email": creds.service_account_email,
                "updated_at": manifest.updated_at,
            }

        import os

        service = build_drive_service(os.environ["GOOGLE_DRIVE_CREDENTIALS_JSON"].strip())
        drive_port = GoogleDriveApiPort(service)

    selected = [s for s in drive_config.sources if (not source_ids or s.id in source_ids)]
    results = []
    for source in selected:
        if not source.enabled:
            results.append({"source_id": source.id, "status": "disabled", "skipped": True})
            continue
        result = sync_drive_source(
            clients_root=clients_root,
            client_id=cid,
            source=source,
            settings=sync_settings,
            manifest=manifest,
            drive=drive_port,
            include_shared_drives=drive_config.defaults.include_shared_drives,
        )
        record = manifest.sources.get(source.id)
        if record is not None:
            record.config_updated_at = drive_config.updated_at
        results.append(
            {
                "source_id": result.source_id,
                "status": result.status,
                "files_discovered": result.files_discovered,
                "files_synced": result.files_synced,
                "files_failed": result.files_failed,
                "files_skipped": result.files_skipped,
                "files_skipped_unchanged": result.files_skipped_unchanged,
                "sync_summary": result.sync_summary,
                "failure_breakdown": result.failure_breakdown,
                "last_error": result.last_error,
                "admin_message": result.admin_message,
            }
        )

    save_drive_sync_manifest(clients_root, cid, manifest)
    return {
        "sources": results,
        "credentials_configured": creds.configured,
        "service_account_email": creds.service_account_email,
        "updated_at": manifest.updated_at,
    }


def list_drive_sources_with_status(
    *,
    clients_root: Path,
    client_id: str,
    config_loader: TenantConfigLoader,
) -> dict[str, Any]:
    cid = safe_client_id(client_id)
    config_dir = client_config_dir(clients_root, cid)
    drive_config = load_drive_sources(config_dir)
    manifest = load_drive_sync_manifest(clients_root, cid)
    creds = load_drive_credentials_info()

    rows: list[dict[str, Any]] = []
    for source in drive_config.sources:
        sync_record = manifest.sources.get(source.id)
        status = resolve_runtime_status(
            source_enabled=source.enabled,
            sync_record=sync_record,
            config_updated_at=drive_config.updated_at,
        )
        rows.append(
            {
                "id": source.id,
                "folder_id": source.folder_id,
                "title": source.title,
                "enabled": source.enabled,
                "recursive": source.recursive,
                "max_files": source.max_files,
                "status": status,
                "last_synced_at": sync_record.last_synced_at if sync_record else None,
                "files_discovered": sync_record.files_discovered if sync_record else 0,
                "files_synced": sync_record.files_synced if sync_record else 0,
                "files_failed": sync_record.files_failed if sync_record else 0,
                "files_skipped": sync_record.files_skipped if sync_record else 0,
                "files_skipped_unchanged": sync_record.files_skipped_unchanged if sync_record else 0,
                "sync_summary": sync_record.sync_summary if sync_record else None,
                "failure_breakdown": sync_record.failure_breakdown if sync_record else {},
                "last_error": sync_record.last_error if sync_record else None,
                "admin_message": sync_record.admin_message if sync_record else None,
            }
        )
    return {
        "sources": rows,
        "credentials_configured": creds.configured,
        "service_account_email": creds.service_account_email,
        "credentials_error": creds.error,
    }


def _missing_credentials_record(message: str):
    from packages.core.drive_sources.models import DriveSourceRecord
    from packages.core.ingestion.models import utc_now_iso

    return DriveSourceRecord(
        status="failed_auth",
        last_synced_at=utc_now_iso(),
        last_error="missing_credentials",
        admin_message=message,
    )
