from __future__ import annotations

import fnmatch
from urllib.parse import parse_qsl, urlparse

ASSET_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".svg",
        ".ico",
        ".css",
        ".js",
        ".mjs",
        ".map",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".pdf",
        ".zip",
        ".gz",
        ".mp4",
        ".mp3",
        ".avi",
        ".mov",
        ".xml",
        ".json",
    }
)


def is_asset_url(url: str) -> bool:
    path = (urlparse(url).path or "").lower()
    for ext in ASSET_EXTENSIONS:
        if path.endswith(ext):
            return True
    return False


def has_denied_query(url: str, deny_prefixes: list[str]) -> bool:
    if not deny_prefixes:
        return False
    query = urlparse(url).query
    if not query:
        return False
    for key, _value in parse_qsl(query, keep_blank_values=True):
        lowered = key.lower()
        for prefix in deny_prefixes:
            if lowered.startswith(prefix.lower()):
                return True
    return False


def is_denied_path(url: str, deny_patterns: list[str]) -> bool:
    path = urlparse(url).path or "/"
    lowered = path.lower()
    for pattern in deny_patterns:
        pat = pattern.lower()
        if fnmatch.fnmatch(lowered, pat) or pat in lowered:
            return True
    return False


def should_skip_url(
    url: str,
    *,
    deny_path_patterns: list[str],
    deny_query_prefixes: list[str],
) -> bool:
    if is_asset_url(url):
        return True
    if is_denied_path(url, deny_path_patterns):
        return True
    if has_denied_query(url, deny_query_prefixes):
        return True
    return False
