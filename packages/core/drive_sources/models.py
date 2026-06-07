from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

DriveSourceRuntimeStatus = Literal[
    "configured",
    "synced",
    "synced_with_warnings",
    "failed_auth",
    "failed_extraction",
    "disabled",
    "stale",
]

DriveFileStatus = Literal[
    "synced",
    "skipped_unchanged",
    "failed_extraction",
    "failed_size",
    "failed_unsupported",
    "skipped_trashed",
]

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"


@dataclass
class DriveSourceDefaults:
    recursive: bool = True
    include_shared_drives: bool = True
    max_files_per_root: int = 200


@dataclass
class DriveSourceEntry:
    id: str
    folder_id: str
    title: str | None = None
    enabled: bool = True
    recursive: bool = True
    max_files: int = 200


@dataclass
class DriveSourcesConfig:
    version: int = 1
    updated_at: str | None = None
    defaults: DriveSourceDefaults = field(default_factory=DriveSourceDefaults)
    sources: list[DriveSourceEntry] = field(default_factory=list)


@dataclass
class DriveFileRecord:
    file_id: str
    name: str
    mime_type: str
    status: DriveFileStatus
    modified_time: str | None = None
    content_hash: str | None = None
    cache_file: str | None = None
    web_view_link: str | None = None
    char_count: int = 0
    error: str | None = None
    admin_message: str | None = None


@dataclass
class DriveSourceRecord:
    status: DriveSourceRuntimeStatus = "configured"
    last_synced_at: str | None = None
    files_discovered: int = 0
    files_synced: int = 0
    files_failed: int = 0
    files_skipped: int = 0
    files_skipped_unchanged: int = 0
    sync_summary: str | None = None
    failure_breakdown: dict[str, int] = field(default_factory=dict)
    last_error: str | None = None
    admin_message: str | None = None
    config_updated_at: str | None = None
    files: dict[str, DriveFileRecord] = field(default_factory=dict)


@dataclass
class DriveSyncManifest:
    updated_at: str | None = None
    sources: dict[str, DriveSourceRecord] = field(default_factory=dict)


@dataclass
class DriveSyncSettings:
    max_file_bytes: int = 10_000_000
    global_max_files_per_source: int = 200
    allowed_mime_types: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DriveSyncSettings:
        raw = data or {}
        drive = raw.get("drive_sync") if isinstance(raw.get("drive_sync"), dict) else raw
        if not isinstance(drive, dict):
            drive = {}
        return cls(
            max_file_bytes=int(drive.get("max_file_bytes", 10_000_000)),
            global_max_files_per_source=int(drive.get("global_max_files_per_source", 200)),
            allowed_mime_types=[str(x) for x in (drive.get("allowed_mime_types") or [])],
        )


@dataclass
class DriveSyncRunResult:
    source_id: str
    status: str
    files_discovered: int
    files_synced: int
    files_failed: int
    files_skipped: int
    files_skipped_unchanged: int = 0
    sync_summary: str | None = None
    failure_breakdown: dict[str, int] = field(default_factory=dict)
    last_error: str | None = None
    admin_message: str | None = None
