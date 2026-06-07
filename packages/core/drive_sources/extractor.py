from __future__ import annotations

import hashlib
import re
from io import BytesIO
from pathlib import Path

from packages.adapters.ingestion.local_upload_extractor import extract_text
from packages.core.drive_sources.models import GOOGLE_DOC_MIME
from packages.core.ingestion.nfc import normalize_text_nfc

MIME_TO_EXT = {
    GOOGLE_DOC_MIME: ".txt",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "text/markdown": ".md",
}


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_extension(mime_type: str, filename: str) -> str:
    if mime_type in MIME_TO_EXT:
        return MIME_TO_EXT[mime_type]
    ext = Path(filename).suffix.lower()
    if ext in {".pdf", ".docx", ".txt", ".md", ".markdown"}:
        return ext if ext != ".markdown" else ".md"
    return ".txt"


def extract_drive_bytes(*, data: bytes, mime_type: str, filename: str) -> tuple[str | None, str | None]:
    if mime_type == GOOGLE_DOC_MIME:
        text = normalize_text_nfc(data.decode("utf-8", errors="replace").strip())
        if not text:
            return None, "empty_extraction"
        return text, None

    ext = cache_extension(mime_type, filename)
    virtual_name = filename if Path(filename).suffix else f"{filename}{ext}"
    result = extract_text(Path(virtual_name), raw_bytes=data)
    if result.unsupported:
        return None, result.reason or "unsupported"
    if result.error or not result.text:
        return None, result.error or "empty_extraction"
    text = normalize_text_nfc(result.text.strip())
    if not text:
        return None, "empty_extraction"
    return text, None


def file_key_for(name: str, file_id: str) -> str:
    from packages.core.drive_sources.validation import sanitize_file_key

    stem = sanitize_file_key(Path(name).stem or "file")
    tail = re.sub(r"[^a-zA-Z0-9]", "", file_id)[-8:] or "file"
    return f"{stem}_{tail}"[:120]
