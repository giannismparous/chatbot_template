from __future__ import annotations

import unicodedata
from pathlib import Path


def normalize_text_nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def normalize_filename_nfc(name: str) -> str:
    return normalize_text_nfc(name)


def normalize_path_filename(path: Path) -> Path:
    """Return path with NFC-normalized final component."""
    if not path.name:
        return path
    return path.parent / normalize_filename_nfc(path.name)
