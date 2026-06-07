from __future__ import annotations

import re

SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
FOLDER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{10,}$")


class DriveSourceValidationError(ValueError):
    pass


def validate_source_id(source_id: str) -> str:
    value = (source_id or "").strip().lower()
    if not SOURCE_ID_RE.match(value):
        raise DriveSourceValidationError(
            "source id must be 3-64 chars, start with a-z/0-9, and use [a-z0-9_-] only."
        )
    return value


def validate_folder_id(folder_id: str) -> str:
    value = (folder_id or "").strip()
    if not value:
        raise DriveSourceValidationError("folder_id is required.")
    if not FOLDER_ID_RE.match(value):
        raise DriveSourceValidationError("folder_id format is invalid.")
    return value


def derive_source_id_from_folder(folder_id: str, title: str | None = None) -> str:
    if title:
        candidate = re.sub(r"[^a-z0-9_-]+", "_", title.strip().lower())[:56].strip("_")
        if candidate and SOURCE_ID_RE.match(candidate):
            return validate_source_id(candidate)
    tail = folder_id[-12:].lower()
    return validate_source_id(f"drive_{tail}")


def clamp_max_files(value: int, *, platform_max: int) -> int:
    files = max(1, int(value))
    return min(files, platform_max)


def sanitize_file_key(name: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9._-]+", "_", (name or "file").strip())[:120].strip("._")
    return base or "file"
