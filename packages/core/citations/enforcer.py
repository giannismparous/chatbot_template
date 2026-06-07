from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from packages.core.citations.models import CitationContext, CitationResult
from packages.core.domain.models import PublicSource

CITATION_MARKER_RE = re.compile(r"\[\s*(\d+)\s*\]")
CITATION_GROUP_RE = re.compile(r"\[\s*(\d+(?:\s*,\s*\d+)+)\s*\]")
CITATION_ANY_RE = re.compile(r"\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]")
URL_RE = re.compile(r"https?://[^\s\])<>\"']+")


def _extract_citation_indices(text: str, valid_indices: set[int]) -> set[int]:
    found: set[int] = set()
    for match in CITATION_MARKER_RE.finditer(text):
        index = int(match.group(1))
        if index in valid_indices:
            found.add(index)
    for match in CITATION_GROUP_RE.finditer(text):
        for part in match.group(1).split(","):
            index = int(part.strip())
            if index in valid_indices:
                found.add(index)
    return found


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


def _is_https_public_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _collect_allowed_urls(context: CitationContext, whitelist: dict[str, Any]) -> set[str]:
    rules = whitelist.get("citation_url_rules") or {}
    allow_only = bool(rules.get("allow_only_whitelisted", True))
    domains = [str(d) for d in (whitelist.get("allowed_public_domains") or [])]

    allowed: set[str] = set()
    for chunk in context.chunks:
        if chunk.source_visibility != "public" or not chunk.citation_url:
            continue
        url = str(chunk.citation_url)
        if not _is_https_public_url(url):
            continue
        if allow_only and domains:
            if _host_allowed(url, domains):
                allowed.add(url)
        elif not allow_only:
            allowed.add(url)
    return allowed


def _build_public_sources(
    context: CitationContext,
    valid_citations: set[int],
    whitelist: dict[str, Any],
) -> list[PublicSource]:
    enforcement = whitelist.get("citation_enforcement") or {}
    include_only_cited = bool(enforcement.get("include_only_cited_sources", True))
    rules = whitelist.get("citation_url_rules") or {}
    allow_only = bool(rules.get("allow_only_whitelisted", True))
    domains = [str(d) for d in (whitelist.get("allowed_public_domains") or [])]

    public: list[PublicSource] = []
    for chunk in context.chunks:
        if include_only_cited and chunk.index not in valid_citations:
            continue
        if chunk.source_visibility != "public" or not chunk.citation_url:
            continue
        url = str(chunk.citation_url)
        if not _is_https_public_url(url):
            continue
        if allow_only:
            if not domains:
                continue
            if not _host_allowed(url, domains):
                continue

        public.append(
            PublicSource(
                index=chunk.index,
                title=chunk.title,
                url=url,
                score=round(chunk.score, 4),
            )
        )
    return _dedupe_public_sources_by_url(public)


def _dedupe_public_sources_by_url(sources: list[PublicSource]) -> list[PublicSource]:
    seen: set[str] = set()
    deduped: list[PublicSource] = []
    for source in sorted(sources, key=lambda s: s.index):
        url = str(source.url).rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        deduped.append(source)
    return deduped


def _chunk_qualifies_for_public_source(chunk: CitedChunk, whitelist: dict[str, Any]) -> bool:
    if chunk.source_visibility != "public" or not chunk.citation_url:
        return False
    url = str(chunk.citation_url)
    if not _is_https_public_url(url):
        return False
    rules = whitelist.get("citation_url_rules") or {}
    allow_only = bool(rules.get("allow_only_whitelisted", True))
    domains = [str(d) for d in (whitelist.get("allowed_public_domains") or [])]
    if allow_only:
        if not domains:
            return False
        return _host_allowed(url, domains)
    return True


def _chunk_index_to_public_source_index(
    context: CitationContext,
    public_sources: list[PublicSource],
    whitelist: dict[str, Any],
) -> dict[int, int]:
    url_to_source_index = {str(source.url).rstrip("/"): source.index for source in public_sources}
    mapping: dict[int, int] = {}
    for chunk in context.chunks:
        if not _chunk_qualifies_for_public_source(chunk, whitelist):
            continue
        url = str(chunk.citation_url).rstrip("/")
        source_index = url_to_source_index.get(url)
        if source_index is not None:
            mapping[chunk.index] = source_index
    return mapping


def _sanitize_public_citation_markers(
    answer: str,
    index_map: dict[int, int],
    *,
    stripped_citations: list[int],
) -> tuple[str, set[int]]:
    visible: set[int] = set()

    def _rewrite(match: re.Match[str]) -> str:
        raw_indices = [int(part.strip()) for part in match.group(1).split(",")]
        mapped = sorted({index_map[index] for index in raw_indices if index in index_map})
        for index in raw_indices:
            if index not in index_map:
                stripped_citations.append(index)
        if not mapped:
            return ""
        visible.update(mapped)
        if len(mapped) == 1:
            return f"[{mapped[0]}]"
        return "[" + ", ".join(str(index) for index in mapped) + "]"

    cleaned = CITATION_ANY_RE.sub(_rewrite, answer)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +([,.;:!?])", r"\1", cleaned)
    return cleaned.strip(), visible


def enforce_citations(
    answer: str,
    context: CitationContext,
    whitelist: dict[str, Any],
) -> CitationResult:
    rules = whitelist.get("citation_url_rules") or {}
    strip_llm_urls = bool(rules.get("strip_llm_urls", True))
    valid_indices = context.valid_indices
    stripped_citations: list[int] = []

    def _replace_marker(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if index in valid_indices:
            return match.group(0)
        stripped_citations.append(index)
        return ""

    cleaned = CITATION_MARKER_RE.sub(_replace_marker, answer)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)

    stripped_urls: list[str] = []
    if strip_llm_urls:
        allowed_urls = _collect_allowed_urls(context, whitelist)

        def _replace_url(match: re.Match[str]) -> str:
            raw = match.group(0)
            url = raw.rstrip(".,);]")
            if url in allowed_urls:
                return raw
            if not allowed_urls:
                rules_inner = whitelist.get("citation_url_rules") or {}
                if not rules_inner.get("allow_only_whitelisted", True):
                    for chunk in context.chunks:
                        if chunk.citation_url and url == str(chunk.citation_url):
                            return raw
            stripped_urls.append(url)
            return ""

        cleaned = URL_RE.sub(_replace_url, cleaned)

    valid_citations = _extract_citation_indices(cleaned, valid_indices)
    public_sources = _build_public_sources(context, valid_citations, whitelist)
    index_map = _chunk_index_to_public_source_index(context, public_sources, whitelist)
    cleaned, visible_citations = _sanitize_public_citation_markers(
        cleaned,
        index_map,
        stripped_citations=stripped_citations,
    )

    return CitationResult(
        answer=cleaned,
        public_sources=public_sources,
        valid_citations=visible_citations,
        stripped_citations=stripped_citations,
        stripped_urls=stripped_urls,
    )
