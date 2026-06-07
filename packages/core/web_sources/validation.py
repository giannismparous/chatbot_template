from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse
from packages.core.ingestion.source_mapping import _whitelist_allows_url, validate_citation_url

SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


class WebSourceValidationError(ValueError):
    pass


def validate_source_id(source_id: str) -> str:
    value = (source_id or "").strip().lower()
    if not SOURCE_ID_RE.match(value):
        raise WebSourceValidationError(
            "source id must be 3-64 chars, start with a-z/0-9, and use [a-z0-9_-] only."
        )
    return value


def _is_private_or_local_host(host: str) -> bool:
    host = host.strip().lower().rstrip(".")
    if not host:
        return True
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return True
    if host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        return bool(
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        )
    except ValueError:
        return False


def validate_public_http_url(url: str) -> str:
    try:
        normalized = validate_citation_url(url)
    except Exception as exc:
        raise WebSourceValidationError(str(exc)) from exc
    parsed = urlparse(normalized)
    host = parsed.hostname or ""
    if _is_private_or_local_host(host):
        raise WebSourceValidationError("URL host must not be localhost or a private network address.")
    return normalized


def normalize_page_url(url: str) -> str:
    value = validate_public_http_url(url)
    parsed = urlparse(value)
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    normalized = parsed._replace(fragment="", params="").geturl()
    if parsed.path in {"", "/"} and normalized.endswith("/"):
        return normalized
    return normalized.rstrip("/") if parsed.path not in {"", "/"} else normalized


def registrable_domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host:
        raise WebSourceValidationError("URL must include a host.")
    return host


def same_registrable_domain(url_a: str, url_b: str) -> bool:
    return registrable_domain(url_a) == registrable_domain(url_b)


def domain_whitelisted(url: str, whitelist: dict) -> bool:
    return _whitelist_allows_url(url, whitelist)


def clamp_depth(value: int, *, platform_max: int) -> int:
    depth = max(0, int(value))
    return min(depth, platform_max)


def clamp_pages(value: int, *, platform_max: int) -> int:
    pages = max(1, int(value))
    return min(pages, platform_max)


def derive_source_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "site").lower().removeprefix("www.").replace(".", "_")
    slug = (parsed.path.strip("/") or "index").replace("/", "_")
    candidate = f"{host}_{slug}"[:64].strip("_")
    candidate = re.sub(r"[^a-z0-9_-]+", "_", candidate.lower())
    candidate = candidate.strip("_") or "web_source"
    if not SOURCE_ID_RE.match(candidate):
        candidate = f"web_{candidate[:56]}".strip("_")
    return validate_source_id(candidate)


def validate_render_mode(value: Any) -> str:
    mode = str(value or "static").strip().lower()
    if mode not in {"static", "playwright"}:
        raise WebSourceValidationError("render_mode must be static or playwright.")
    return mode


def validate_wait_until(value: Any) -> str:
    wait = str(value or "networkidle").strip().lower()
    if wait not in {"networkidle", "domcontentloaded", "load"}:
        raise WebSourceValidationError("wait_until must be networkidle, domcontentloaded, or load.")
    return wait


def validate_wait_selector(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if "javascript:" in lowered or "<" in text:
        raise WebSourceValidationError("wait_selector must be a simple CSS selector.")
    return text
