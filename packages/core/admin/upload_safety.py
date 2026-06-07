from __future__ import annotations

import re
from pathlib import PurePosixPath

BLOCKED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".exe",
        ".dll",
        ".bat",
        ".cmd",
        ".sh",
        ".ps1",
        ".js",
        ".jar",
        ".zip",
        ".tar",
        ".gz",
        ".7z",
        ".rar",
        ".env",
        ".pem",
        ".key",
        ".p12",
        ".pfx",
    }
)

SECRET_LIKE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|[_\-.])secrets?([_\-.]|$)", re.I),
    re.compile(r"(^|[_\-.])credentials?([_\-.]|$)", re.I),
    re.compile(r"(^|[_\-.])\.env([_\-.]|$)", re.I),
    re.compile(r"service[_-]?account", re.I),
    re.compile(r"private[_-]?key", re.I),
    re.compile(r"id[_-]?rsa", re.I),
    re.compile(r"admin[_-]?token", re.I),
    re.compile(r"api[_-]?key", re.I),
)


class UploadValidationError(ValueError):
    pass


def validate_upload_relative_path(relative_path: str) -> str:
    raw = (relative_path or "").strip()
    if not raw:
        raise UploadValidationError("Missing upload path.")
    if "\x00" in raw:
        raise UploadValidationError("Null byte in path.")
    if raw.startswith("/") or raw.startswith("\\"):
        raise UploadValidationError("Absolute paths are not allowed.")
    if "\\" in raw:
        raise UploadValidationError("Backslashes are not allowed.")
    if ".." in PurePosixPath(raw.replace("\\", "/")).parts:
        raise UploadValidationError("Path traversal is not allowed.")

    normalized = PurePosixPath(raw.replace("\\", "/")).as_posix()
    parts = [p for p in normalized.split("/") if p]
    if not parts:
        raise UploadValidationError("Invalid upload path.")
    filename = parts[-1]
    _validate_filename(filename)
    return normalized


def _validate_filename(filename: str) -> None:
    if not filename or filename in {".", ".."}:
        raise UploadValidationError("Invalid filename.")
    if "\x00" in filename:
        raise UploadValidationError("Null byte in filename.")
    lower = filename.lower()
    for pattern in SECRET_LIKE_PATTERNS:
        if pattern.search(lower):
            raise UploadValidationError("Secret-like filename rejected.")
    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()
    if ext in BLOCKED_EXTENSIONS:
        raise UploadValidationError(f"Blocked file extension: {ext}")
