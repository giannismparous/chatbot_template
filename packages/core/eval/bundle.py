from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from packages.core.ingestion.paths import knowledge_index_path


def build_cited_doc_bundle(
    zip_path: Path,
    *,
    clients_root: Path,
    client_id: str,
    cases: list[dict[str, Any]],
    index_version: str | None,
    public_only: bool,
) -> None:
    if not index_version:
        return
    index_path = knowledge_index_path(clients_root, client_id, index_version)
    if not index_path.is_file():
        return

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    chunks = payload.get("chunks") if isinstance(payload, dict) else payload
    if not isinstance(chunks, list):
        return

    by_url: dict[str, dict] = {}
    for raw in chunks:
        if not isinstance(raw, dict):
            continue
        for key in ("citation_url", "internal_url", "url"):
            url = raw.get(key)
            if url:
                by_url[str(url)] = raw

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for case in cases:
            for source in case.get("sources") or []:
                url = str(source.get("url") or "")
                if not url or url in seen:
                    continue
                if public_only and not _is_public_http(url):
                    continue
                if public_only and any(x in url.lower() for x in ("uploads/", "internal://", "drive.google.com")):
                    continue
                seen.add(url)
                chunk = by_url.get(url)
                title = str(source.get("title") or "source")
                safe_name = _safe_filename(f"{source.get('index', 0)}_{title}.txt")
                body = _chunk_body(chunk) if chunk else f"URL: {url}\n(no indexed body matched)\n"
                header = f"url: {url}\nindex_version: {index_version}\n\n"
                zf.writestr(safe_name, header + body)


def _is_public_http(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _chunk_body(chunk: dict | None) -> str:
    if not chunk:
        return ""
    content = str(chunk.get("content") or chunk.get("text") or "")
    return content[:8000]


def _safe_filename(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)
    return cleaned[:120] or "source.txt"
