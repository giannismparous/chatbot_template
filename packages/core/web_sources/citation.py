from __future__ import annotations

from typing import Any, Literal

from packages.core.ingestion.source_mapping import (
    ResolvedCitationMeta,
    validate_citation_url,
    _whitelist_allows_url,
)
from packages.core.web_sources.models import JS_RENDER_HINT, PLAYWRIGHT_LOW_CONTENT_HINT

CitationStatus = Literal[
    "internal_only",
    "public_configured",
    "blocked_by_whitelist",
    "invalid_url",
]


def resolve_web_citation(
    *,
    page_url: str,
    title: str,
    whitelist: dict[str, Any],
) -> ResolvedCitationMeta:
    default_title = title.strip() or page_url
    try:
        citation_url = validate_citation_url(page_url)
    except Exception:
        return ResolvedCitationMeta(
            title=default_title,
            citation_url=None,
            source_visibility="internal",
            status="invalid_url",
            configured_citation_url=page_url,
            configured_title=default_title,
        )

    if not _whitelist_allows_url(citation_url, whitelist):
        return ResolvedCitationMeta(
            title=default_title,
            citation_url=None,
            source_visibility="internal",
            status="blocked_by_whitelist",
            configured_citation_url=citation_url,
            configured_title=default_title,
        )

    return ResolvedCitationMeta(
        title=default_title,
        citation_url=citation_url,
        source_visibility="public",
        status="public_configured",
        configured_citation_url=citation_url,
        configured_title=default_title,
    )


def apply_web_citation_to_chunk(chunk, *, page_url: str, title: str, whitelist: dict[str, Any]):
    resolved = resolve_web_citation(page_url=page_url, title=title, whitelist=whitelist)
    chunk.title = resolved.title
    chunk.citation_url = resolved.citation_url
    chunk.source_visibility = resolved.source_visibility
    return chunk


def low_content_message(char_count: int, *, min_chars: int, playwright: bool = False) -> str:
    hint = PLAYWRIGHT_LOW_CONTENT_HINT if playwright else JS_RENDER_HINT
    if char_count <= 0:
        return hint
    return f"Extracted only {char_count} characters (minimum {min_chars}). {hint}"
