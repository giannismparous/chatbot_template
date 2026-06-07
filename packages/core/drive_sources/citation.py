from __future__ import annotations

from typing import Any

from packages.core.ingestion.source_mapping import (
    ResolvedCitationMeta,
    SourceMappingConfig,
    SourceMappingEntry,
    _whitelist_allows_url,
    validate_citation_url,
)


def drive_mapping_key(source_id: str, file_key: str) -> str:
    return f"{source_id}/{file_key}"


def resolve_drive_citation(
    *,
    source_id: str,
    file_key: str,
    title: str,
    mapping: SourceMappingConfig,
    whitelist: dict[str, Any],
) -> ResolvedCitationMeta:
    default_title = title.strip() or f"{source_id}/{file_key}"
    key = drive_mapping_key(source_id, file_key)
    entry = mapping.drive.get(key)

    if entry is None or not entry.citation_url.strip():
        return ResolvedCitationMeta(
            title=default_title,
            citation_url=None,
            source_visibility="internal",
            status="internal_only",
        )

    configured_url = entry.citation_url.strip()
    configured_title = (entry.title or default_title).strip()[:200]

    if "drive.google.com" in configured_url.lower():
        return ResolvedCitationMeta(
            title=configured_title,
            citation_url=None,
            source_visibility="internal",
            status="invalid_url",
            configured_citation_url=configured_url,
            configured_title=configured_title,
        )

    try:
        validate_citation_url(configured_url)
    except Exception:
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


def apply_drive_citation_to_chunk(
    chunk,
    *,
    source_id: str,
    file_key: str,
    title: str,
    mapping: SourceMappingConfig,
    whitelist: dict[str, Any],
):
    resolved = resolve_drive_citation(
        source_id=source_id,
        file_key=file_key,
        title=title,
        mapping=mapping,
        whitelist=whitelist,
    )
    chunk.title = resolved.title
    chunk.citation_url = resolved.citation_url
    chunk.source_visibility = resolved.source_visibility
    return chunk
