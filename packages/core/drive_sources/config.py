from __future__ import annotations

from pathlib import Path
from typing import Any

from packages.config.loaders import load_yaml, save_yaml
from packages.core.drive_sources.models import DriveSourceDefaults, DriveSourceEntry, DriveSourcesConfig
from packages.core.drive_sources.paths import drive_sources_config_path
from packages.core.drive_sources.validation import (
    DriveSourceValidationError,
    clamp_max_files,
    derive_source_id_from_folder,
    validate_folder_id,
    validate_source_id,
)
from packages.core.ingestion.models import utc_now_iso


def empty_drive_sources() -> DriveSourcesConfig:
    return DriveSourcesConfig(version=1, updated_at=None, defaults=DriveSourceDefaults(), sources=[])


def load_drive_sources(config_dir: Path) -> DriveSourcesConfig:
    path = drive_sources_config_path(config_dir)
    if not path.is_file():
        return empty_drive_sources()
    raw = load_yaml(str(path))
    if not isinstance(raw, dict):
        return empty_drive_sources()
    return parse_drive_sources_document(raw)


def parse_drive_sources_document(raw: dict[str, Any]) -> DriveSourcesConfig:
    defaults_raw = raw.get("defaults") or {}
    defaults = DriveSourceDefaults(
        recursive=bool(defaults_raw.get("recursive", True)),
        include_shared_drives=bool(defaults_raw.get("include_shared_drives", True)),
        max_files_per_root=int(defaults_raw.get("max_files_per_root", 200)),
    )
    sources_raw = raw.get("sources") or []
    if not isinstance(sources_raw, list):
        raise DriveSourceValidationError("sources must be a list.")

    sources: list[DriveSourceEntry] = []
    seen: set[str] = set()
    for item in sources_raw:
        if not isinstance(item, dict):
            raise DriveSourceValidationError("Each source must be an object.")
        source_id = validate_source_id(str(item.get("id") or ""))
        if source_id in seen:
            raise DriveSourceValidationError(f"Duplicate source id: {source_id}")
        seen.add(source_id)
        sources.append(
            DriveSourceEntry(
                id=source_id,
                folder_id=validate_folder_id(str(item.get("folder_id") or "")),
                title=_optional_str(item.get("title")),
                enabled=bool(item.get("enabled", True)),
                recursive=bool(item.get("recursive", defaults.recursive)),
                max_files=int(item.get("max_files", defaults.max_files_per_root)),
            )
        )
    return DriveSourcesConfig(
        version=int(raw.get("version") or 1),
        updated_at=_optional_str(raw.get("updated_at")),
        defaults=defaults,
        sources=sources,
    )


def save_drive_sources(config_dir: Path, config: DriveSourcesConfig) -> None:
    payload = {
        "version": config.version,
        "updated_at": config.updated_at or utc_now_iso(),
        "defaults": {
            "recursive": config.defaults.recursive,
            "include_shared_drives": config.defaults.include_shared_drives,
            "max_files_per_root": config.defaults.max_files_per_root,
        },
        "sources": [
            {
                "id": source.id,
                "folder_id": source.folder_id,
                **({"title": source.title} if source.title else {}),
                "enabled": source.enabled,
                **({"recursive": source.recursive} if source.recursive != config.defaults.recursive else {}),
                **({"max_files": source.max_files} if source.max_files != config.defaults.max_files_per_root else {}),
            }
            for source in config.sources
        ],
    }
    save_yaml(str(drive_sources_config_path(config_dir)), payload)


def add_drive_source(
    config_dir: Path,
    *,
    folder_id: str,
    title: str | None,
    enabled: bool,
    recursive: bool,
    max_files: int,
    source_id: str | None,
    sync_settings: dict[str, Any] | None = None,
) -> DriveSourcesConfig:
    from packages.core.drive_sources.models import DriveSyncSettings

    settings = DriveSyncSettings.from_dict(sync_settings or {})
    config = load_drive_sources(config_dir)
    normalized_folder = validate_folder_id(folder_id)
    sid = validate_source_id(source_id or derive_source_id_from_folder(normalized_folder, title))
    if any(s.id == sid for s in config.sources):
        raise DriveSourceValidationError(f"Source id already exists: {sid}")

    config.sources.append(
        DriveSourceEntry(
            id=sid,
            folder_id=normalized_folder,
            title=_optional_str(title),
            enabled=enabled,
            recursive=recursive,
            max_files=clamp_max_files(max_files, platform_max=settings.global_max_files_per_source),
        )
    )
    config.updated_at = utc_now_iso()
    save_drive_sources(config_dir, config)
    return config


def remove_drive_source(config_dir: Path, source_id: str) -> DriveSourcesConfig:
    sid = validate_source_id(source_id)
    config = load_drive_sources(config_dir)
    config.sources = [s for s in config.sources if s.id != sid]
    config.updated_at = utc_now_iso()
    save_drive_sources(config_dir, config)
    return config


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
