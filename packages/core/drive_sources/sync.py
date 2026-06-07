from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from packages.core.drive_sources.extractor import (
    cache_extension,
    content_hash,
    extract_drive_bytes,
    file_key_for,
)
from packages.core.drive_sources.models import (
    GOOGLE_DOC_MIME,
    GOOGLE_FOLDER_MIME,
    DriveFileRecord,
    DriveSourceEntry,
    DriveSourceRecord,
    DriveSyncManifest,
    DriveSyncRunResult,
    DriveSyncSettings,
)
from packages.core.drive_sources.paths import drive_cache_files_dir
from packages.core.drive_sources.summary import (
    build_sync_summary,
    compute_source_status,
    failure_breakdown,
    normalize_file_error,
)
from packages.core.ingestion.models import utc_now_iso

DEFAULT_ALLOWED_MIMES = {
    GOOGLE_DOC_MIME,
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
}


@dataclass
class DriveRemoteFile:
    file_id: str
    name: str
    mime_type: str
    modified_time: str | None
    web_view_link: str | None
    trashed: bool = False
    size: int | None = None


class DrivePort(Protocol):
    def list_files(self, folder_id: str, *, recursive: bool, include_shared_drives: bool) -> list[DriveRemoteFile]:
        ...

    def download_file(self, file_id: str, mime_type: str) -> bytes:
        ...


def sync_drive_source(
    *,
    clients_root: Path,
    client_id: str,
    source: DriveSourceEntry,
    settings: DriveSyncSettings,
    manifest: DriveSyncManifest,
    drive: DrivePort,
    include_shared_drives: bool = True,
) -> DriveSyncRunResult:
    files_dir = drive_cache_files_dir(clients_root, client_id) / source.id
    files_dir.mkdir(parents=True, exist_ok=True)

    allowed_mimes = set(settings.allowed_mime_types or DEFAULT_ALLOWED_MIMES)
    max_files = min(source.max_files, settings.global_max_files_per_source)

    try:
        remote_files = drive.list_files(
            source.folder_id,
            recursive=source.recursive,
            include_shared_drives=include_shared_drives,
        )
    except Exception as exc:
        return _auth_failure(source, manifest, str(exc))

    files: dict[str, DriveFileRecord] = {}
    synced = failed = skipped = skipped_unchanged = 0
    last_error = None
    files_discovered = len(remote_files)

    processed = 0
    for remote in remote_files:
        if processed >= max_files:
            break
        processed += 1
        if remote.trashed:
            files[remote.file_id] = DriveFileRecord(
                file_id=remote.file_id,
                name=remote.name,
                mime_type=remote.mime_type,
                status="skipped_trashed",
                modified_time=remote.modified_time,
                web_view_link=remote.web_view_link,
                error="trashed",
            )
            skipped += 1
            continue

        if remote.mime_type not in allowed_mimes:
            files[remote.file_id] = DriveFileRecord(
                file_id=remote.file_id,
                name=remote.name,
                mime_type=remote.mime_type,
                status="failed_unsupported",
                modified_time=remote.modified_time,
                web_view_link=remote.web_view_link,
                error=f"unsupported_mime:{remote.mime_type}",
            )
            failed += 1
            continue

        if remote.size is not None and remote.size > settings.max_file_bytes:
            files[remote.file_id] = DriveFileRecord(
                file_id=remote.file_id,
                name=remote.name,
                mime_type=remote.mime_type,
                status="failed_size",
                modified_time=remote.modified_time,
                web_view_link=remote.web_view_link,
                error="file_too_large",
                admin_message=f"File exceeds max size ({settings.max_file_bytes} bytes).",
            )
            failed += 1
            last_error = "file_too_large"
            continue

        prior = manifest.sources.get(source.id)
        prior_file = prior.files.get(remote.file_id) if prior else None
        if prior_file and prior_file.modified_time == remote.modified_time and prior_file.content_hash:
            key = file_key_for(remote.name, remote.file_id)
            cache_name = prior_file.cache_file or f"{key}.txt"
            cache_path = files_dir / cache_name
            if cache_path.is_file() and prior_file.status in {"synced", "skipped_unchanged"}:
                files[remote.file_id] = DriveFileRecord(
                    file_id=remote.file_id,
                    name=remote.name,
                    mime_type=remote.mime_type,
                    status="skipped_unchanged",
                    modified_time=remote.modified_time,
                    content_hash=prior_file.content_hash,
                    cache_file=cache_name,
                    web_view_link=remote.web_view_link,
                    char_count=prior_file.char_count,
                )
                skipped += 1
                skipped_unchanged += 1
                continue

        try:
            data = drive.download_file(remote.file_id, remote.mime_type)
        except Exception as exc:
            files[remote.file_id] = DriveFileRecord(
                file_id=remote.file_id,
                name=remote.name,
                mime_type=remote.mime_type,
                status="failed_extraction",
                modified_time=remote.modified_time,
                web_view_link=remote.web_view_link,
                error=f"download_failed:{exc}",
            )
            failed += 1
            last_error = str(exc)
            continue

        if len(data) > settings.max_file_bytes:
            files[remote.file_id] = DriveFileRecord(
                file_id=remote.file_id,
                name=remote.name,
                mime_type=remote.mime_type,
                status="failed_size",
                modified_time=remote.modified_time,
                web_view_link=remote.web_view_link,
                error="file_too_large",
            )
            failed += 1
            continue

        text, extract_error = extract_drive_bytes(data=data, mime_type=remote.mime_type, filename=remote.name)
        key = file_key_for(remote.name, remote.file_id)
        ext = cache_extension(remote.mime_type, remote.name)
        cache_name = f"{key}.txt" if ext != ".txt" else f"{key}.txt"

        if extract_error or not text:
            friendly_error = normalize_file_error(extract_error)
            files[remote.file_id] = DriveFileRecord(
                file_id=remote.file_id,
                name=remote.name,
                mime_type=remote.mime_type,
                status="failed_extraction",
                modified_time=remote.modified_time,
                web_view_link=remote.web_view_link,
                error=extract_error or "empty_extraction",
                admin_message=friendly_error,
            )
            failed += 1
            last_error = extract_error or "empty_extraction"
            continue

        digest = content_hash(text)
        if prior_file and prior_file.content_hash == digest and prior_file.cache_file:
            cache_path = files_dir / prior_file.cache_file
            if cache_path.is_file():
                files[remote.file_id] = DriveFileRecord(
                    file_id=remote.file_id,
                    name=remote.name,
                    mime_type=remote.mime_type,
                    status="skipped_unchanged",
                    modified_time=remote.modified_time,
                    content_hash=digest,
                    cache_file=prior_file.cache_file,
                    web_view_link=remote.web_view_link,
                    char_count=len(text),
                )
                skipped += 1
                skipped_unchanged += 1
                continue

        cache_path = files_dir / cache_name
        cache_path.write_text(text, encoding="utf-8")
        files[remote.file_id] = DriveFileRecord(
            file_id=remote.file_id,
            name=remote.name,
            mime_type=remote.mime_type,
            status="synced",
            modified_time=remote.modified_time,
            content_hash=digest,
            cache_file=cache_name,
            web_view_link=remote.web_view_link,
            char_count=len(text),
        )
        synced += 1

    breakdown = failure_breakdown(files)
    source_status = compute_source_status(
        synced=synced,
        failed=failed,
        skipped_unchanged=skipped_unchanged,
        files=files,
    )
    sync_summary = build_sync_summary(
        status=source_status,
        files_discovered=files_discovered,
        files_synced=synced,
        files_skipped_unchanged=skipped_unchanged,
        files_failed=failed,
        failure_breakdown=breakdown,
    )
    manifest.sources[source.id] = DriveSourceRecord(
        status=source_status,
        last_synced_at=utc_now_iso(),
        files_discovered=files_discovered,
        files_synced=synced,
        files_failed=failed,
        files_skipped=skipped,
        files_skipped_unchanged=skipped_unchanged,
        sync_summary=sync_summary,
        failure_breakdown=breakdown,
        last_error=last_error,
        admin_message=sync_summary,
        files=files,
    )
    return DriveSyncRunResult(
        source_id=source.id,
        status=source_status,
        files_discovered=files_discovered,
        files_synced=synced,
        files_failed=failed,
        files_skipped=skipped,
        files_skipped_unchanged=skipped_unchanged,
        sync_summary=sync_summary,
        failure_breakdown=breakdown,
        last_error=last_error,
        admin_message=sync_summary,
    )


def _auth_failure(source: DriveSourceEntry, manifest: DriveSyncManifest, message: str) -> DriveSyncRunResult:
    admin = (
        "Drive authentication failed. Set GOOGLE_DRIVE_CREDENTIALS_JSON and share the folder "
        "with the service account email."
    )
    manifest.sources[source.id] = DriveSourceRecord(
        status="failed_auth",
        last_synced_at=utc_now_iso(),
        last_error="drive_auth_failed",
        admin_message=admin,
        files={},
    )
    return DriveSyncRunResult(
        source_id=source.id,
        status="failed_auth",
        files_discovered=0,
        files_synced=0,
        files_failed=1,
        files_skipped=0,
        last_error=message,
        admin_message=admin,
    )


class GoogleDriveApiPort:
    def __init__(self, service) -> None:
        self._service = service

    def list_files(self, folder_id: str, *, recursive: bool, include_shared_drives: bool) -> list[DriveRemoteFile]:
        queue = [folder_id]
        visited: set[str] = set()
        gathered: list[DriveRemoteFile] = []
        fields = "nextPageToken, files(id,name,mimeType,modifiedTime,webViewLink,trashed,size)"
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            page_token = None
            while True:
                resp = (
                    self._service.files()
                    .list(
                        q=f"'{current}' in parents and trashed = false",
                        fields=fields,
                        pageToken=page_token,
                        supportsAllDrives=include_shared_drives,
                        includeItemsFromAllDrives=include_shared_drives,
                        pageSize=200,
                    )
                    .execute()
                )
                for item in resp.get("files") or []:
                    mime = item.get("mimeType") or ""
                    if mime == GOOGLE_FOLDER_MIME and recursive:
                        queue.append(item["id"])
                        continue
                    gathered.append(
                        DriveRemoteFile(
                            file_id=item["id"],
                            name=item.get("name") or "Untitled",
                            mime_type=mime,
                            modified_time=item.get("modifiedTime"),
                            web_view_link=item.get("webViewLink"),
                            trashed=bool(item.get("trashed")),
                            size=int(item["size"]) if item.get("size") is not None else None,
                        )
                    )
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
        return gathered

    def download_file(self, file_id: str, mime_type: str) -> bytes:
        if mime_type == GOOGLE_DOC_MIME:
            req = self._service.files().export_media(fileId=file_id, mimeType="text/plain")
        else:
            req = self._service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        from googleapiclient.http import MediaIoBaseDownload

        downloader = MediaIoBaseDownload(fh, req)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return fh.getvalue()


class MockDrivePort:
    def __init__(self, files_by_folder: dict[str, list[DriveRemoteFile]], downloads: dict[str, bytes]) -> None:
        self._files_by_folder = files_by_folder
        self._downloads = downloads

    def list_files(self, folder_id: str, *, recursive: bool, include_shared_drives: bool) -> list[DriveRemoteFile]:
        return list(self._files_by_folder.get(folder_id, []))

    def download_file(self, file_id: str, mime_type: str) -> bytes:
        if file_id not in self._downloads:
            raise RuntimeError(f"missing download for {file_id}")
        return self._downloads[file_id]
