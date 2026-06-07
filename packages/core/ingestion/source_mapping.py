from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from packages.config.loaders import load_yaml, save_yaml
from packages.core.admin.upload_safety import UploadValidationError, validate_upload_relative_path
from packages.core.ingestion.models import KnowledgeChunk, utc_now_iso

CitationStatus = Literal[
    "internal_only",
    "public_configured",
    "blocked_by_whitelist",
    "invalid_url",
]

BLOCKED_URL_SCHEMES = frozenset({"file", "javascript", "data", "internal", "drive"})
TITLE_MAX_LEN = 200


class SourceMappingValidationError(ValueError):
    pass


@dataclass
class SourceMappingEntry:
    citation_url: str
    title: str | None = None
    source_visibility: str = "public"
    updated_at: str | None = None


@dataclass
class SourceMappingConfig:
    version: int = 1
    updated_at: str | None = None
    uploads: dict[str, SourceMappingEntry] = field(default_factory=dict)
    drive: dict[str, SourceMappingEntry] = field(default_factory=dict)


@dataclass
class ResolvedCitationMeta:
    title: str
    citation_url: str | None
    source_visibility: Literal["public", "internal"]
    status: CitationStatus
    configured_citation_url: str | None = None
    configured_title: str | None = None


def source_mapping_path(config_dir: Path) -> Path:
    return config_dir / "source_mapping.yaml"


def empty_source_mapping() -> SourceMappingConfig:
    return SourceMappingConfig(version=1, updated_at=None, uploads={}, drive={})


def load_source_mapping(config_dir: Path) -> SourceMappingConfig:
    path = source_mapping_path(config_dir)
    if not path.is_file():
        return empty_source_mapping()
    raw = load_yaml(str(path))
    if not isinstance(raw, dict):
        return empty_source_mapping()
    return parse_source_mapping_document(raw)


def parse_source_mapping_document(raw: dict[str, Any]) -> SourceMappingConfig:
    uploads_raw = raw.get("uploads") or {}
    if not isinstance(uploads_raw, dict):
        raise SourceMappingValidationError("uploads must be a mapping.")

    uploads: dict[str, SourceMappingEntry] = {}
    for rel_path, entry in uploads_raw.items():
        if not isinstance(entry, dict):
            raise SourceMappingValidationError(f"Upload mapping for {rel_path!r} must be an object.")
        safe_path = validate_upload_relative_path(str(rel_path))
        uploads[safe_path] = SourceMappingEntry(
            citation_url=str(entry.get("citation_url") or "").strip(),
            title=_optional_str(entry.get("title")),
            source_visibility=str(entry.get("source_visibility") or "public").strip().lower(),
            updated_at=_optional_str(entry.get("updated_at")),
        )

    version = int(raw.get("version") or 1)
    drive_raw = raw.get("drive") or {}
    if not isinstance(drive_raw, dict):
        raise SourceMappingValidationError("drive must be a mapping.")
    drive: dict[str, SourceMappingEntry] = {}
    for rel_path, entry in drive_raw.items():
        if not isinstance(entry, dict):
            raise SourceMappingValidationError(f"Drive mapping for {rel_path!r} must be an object.")
        safe_path = str(rel_path).strip().replace("\\", "/").strip("/")
        if not safe_path or ".." in safe_path.split("/"):
            raise SourceMappingValidationError(f"Invalid drive mapping path: {rel_path!r}")
        drive[safe_path] = SourceMappingEntry(
            citation_url=str(entry.get("citation_url") or "").strip(),
            title=_optional_str(entry.get("title")),
            source_visibility=str(entry.get("source_visibility") or "public").strip().lower(),
            updated_at=_optional_str(entry.get("updated_at")),
        )

    return SourceMappingConfig(
        version=version,
        updated_at=_optional_str(raw.get("updated_at")),
        uploads=uploads,
        drive=drive,
    )


def validate_source_mapping_document(raw: dict[str, Any], *, whitelist: dict[str, Any]) -> SourceMappingConfig:
    """Validate full document for admin PUT (paths, URLs, visibility)."""
    if not isinstance(raw, dict):
        raise SourceMappingValidationError("source_mapping must be an object.")
    config = parse_source_mapping_document(raw)
    for rel_path, entry in config.uploads.items():
        _validate_entry_fields(rel_path, entry)
        validate_citation_url(entry.citation_url)
        _validate_visibility(entry.source_visibility)
    return config


def save_source_mapping(config_dir: Path, config: SourceMappingConfig) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    now = utc_now_iso()
    config.updated_at = now
    payload: dict[str, Any] = {
        "version": config.version,
        "updated_at": config.updated_at,
        "uploads": {},
    }
    for rel_path, entry in sorted(config.uploads.items()):
        payload["uploads"][rel_path] = {
            "citation_url": entry.citation_url,
            "title": entry.title,
            "source_visibility": entry.source_visibility,
            "updated_at": entry.updated_at or now,
        }
    if config.drive:
        payload["drive"] = {}
        for rel_path, entry in sorted(config.drive.items()):
            payload["drive"][rel_path] = {
                "citation_url": entry.citation_url,
                "title": entry.title,
                "source_visibility": entry.source_visibility,
                "updated_at": entry.updated_at or now,
            }
    save_yaml(str(source_mapping_path(config_dir)), payload)


def upsert_mapping_entry(
    config_dir: Path,
    *,
    rel_path: str,
    citation_url: str,
    title: str | None,
    source_visibility: str,
    whitelist: dict[str, Any],
) -> ResolvedCitationMeta:
    safe_path = validate_upload_relative_path(rel_path)
    url = citation_url.strip()
    visibility = (source_visibility or "public").strip().lower()
    _validate_visibility(visibility)
    validate_citation_url(url)

    config = load_source_mapping(config_dir)
    now = utc_now_iso()
    config.uploads[safe_path] = SourceMappingEntry(
        citation_url=url,
        title=_normalize_title(title, default_filename=Path(safe_path).name),
        source_visibility=visibility,
        updated_at=now,
    )
    save_source_mapping(config_dir, config)
    return resolve_upload_citation(
        rel_path=safe_path,
        filename=Path(safe_path).name,
        entry=config.uploads[safe_path],
        whitelist=whitelist,
    )


def delete_mapping_entry(config_dir: Path, rel_path: str) -> bool:
    safe_path = validate_upload_relative_path(rel_path)
    config = load_source_mapping(config_dir)
    if safe_path not in config.uploads:
        return False
    del config.uploads[safe_path]
    save_source_mapping(config_dir, config)
    return True


def remove_mapping_entry_if_present(config_dir: Path, rel_path: str) -> None:
    try:
        safe_path = validate_upload_relative_path(rel_path)
    except UploadValidationError:
        return
    config = load_source_mapping(config_dir)
    if safe_path in config.uploads:
        del config.uploads[safe_path]
        save_source_mapping(config_dir, config)


def resolve_upload_citation(
    *,
    rel_path: str,
    filename: str,
    entry: SourceMappingEntry | None,
    whitelist: dict[str, Any],
) -> ResolvedCitationMeta:
    default_title = _normalize_title(None, default_filename=filename)
    if entry is None or not entry.citation_url.strip():
        return ResolvedCitationMeta(
            title=default_title,
            citation_url=None,
            source_visibility="internal",
            status="internal_only",
        )

    configured_url = entry.citation_url.strip()
    configured_title = _normalize_title(entry.title, default_filename=filename)

    try:
        validate_citation_url(configured_url)
    except SourceMappingValidationError:
        return ResolvedCitationMeta(
            title=configured_title,
            citation_url=None,
            source_visibility="internal",
            status="invalid_url",
            configured_citation_url=configured_url,
            configured_title=configured_title,
        )

    if entry.source_visibility != "public":
        return ResolvedCitationMeta(
            title=configured_title,
            citation_url=None,
            source_visibility="internal",
            status="internal_only",
            configured_citation_url=configured_url,
            configured_title=configured_title,
        )

    if not _whitelist_allows_url(configured_url, whitelist):
        return ResolvedCitationMeta(
            title=configured_title,
            citation_url=None,
            source_visibility="internal",
            status="blocked_by_whitelist",
            configured_citation_url=configured_url,
            configured_title=configured_title,
        )

    return ResolvedCitationMeta(
        title=configured_title,
        citation_url=configured_url,
        source_visibility="public",
        status="public_configured",
        configured_citation_url=configured_url,
        configured_title=configured_title,
    )


def apply_mapping_to_chunk(
    chunk: KnowledgeChunk,
    *,
    rel_path: str,
    filename: str,
    mapping: SourceMappingConfig,
    whitelist: dict[str, Any],
) -> KnowledgeChunk:
    entry = mapping.uploads.get(rel_path)
    resolved = resolve_upload_citation(
        rel_path=rel_path,
        filename=filename,
        entry=entry,
        whitelist=whitelist,
    )
    chunk.title = resolved.title
    chunk.citation_url = resolved.citation_url
    chunk.source_visibility = resolved.source_visibility
    return chunk


def citation_status_for_upload(
    *,
    rel_path: str,
    filename: str,
    mapping: SourceMappingConfig,
    whitelist: dict[str, Any],
) -> ResolvedCitationMeta:
    entry = mapping.uploads.get(rel_path)
    return resolve_upload_citation(
        rel_path=rel_path,
        filename=filename,
        entry=entry,
        whitelist=whitelist,
    )


def validate_citation_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        raise SourceMappingValidationError("citation_url is required.")
    parsed = urlparse(value)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise SourceMappingValidationError("citation_url must use http:// or https://.")
    if scheme in BLOCKED_URL_SCHEMES:
        raise SourceMappingValidationError(f"Blocked URL scheme: {scheme}.")
    if not parsed.netloc:
        raise SourceMappingValidationError("citation_url must include a host.")
    lowered = value.lower()
    for token in ("uploads/", "drive:", "internal://", "file://", "drive.google.com"):
        if token in lowered:
            raise SourceMappingValidationError(f"citation_url must not contain {token!r}.")
    return value


def _validate_entry_fields(rel_path: str, entry: SourceMappingEntry) -> None:
    validate_upload_relative_path(rel_path)
    if not entry.citation_url.strip():
        raise SourceMappingValidationError(f"citation_url required for upload {rel_path!r}.")
    if entry.title and len(entry.title) > TITLE_MAX_LEN:
        raise SourceMappingValidationError(f"title too long for upload {rel_path!r}.")


def _validate_visibility(value: str) -> None:
    if value not in {"public", "internal"}:
        raise SourceMappingValidationError("source_visibility must be public or internal.")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_title(title: str | None, *, default_filename: str) -> str:
    if title and str(title).strip():
        return str(title).strip()[:TITLE_MAX_LEN]
    return default_filename


def _normalize_host(url: str) -> str:
    host = urlparse(url).hostname or ""
    return host.lower().removeprefix("www.")


def _host_allowed(url: str, domains: list[str]) -> bool:
    host = _normalize_host(url)
    if not host:
        return False
    for domain in domains:
        allowed = domain.lower().removeprefix("www.")
        if host == allowed or host.endswith(f".{allowed}"):
            return True
    return False


def _whitelist_allows_url(url: str, whitelist: dict[str, Any]) -> bool:
    rules = whitelist.get("citation_url_rules") or {}
    allow_only = bool(rules.get("allow_only_whitelisted", True))
    domains = [str(d) for d in (whitelist.get("allowed_public_domains") or []) if str(d).strip()]
    if allow_only:
        if not domains:
            return False
        return _host_allowed(url, domains)
    return True
