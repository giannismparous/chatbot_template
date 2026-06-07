from __future__ import annotations

import unicodedata
from typing import Any


def normalize_query(raw: str, locale: dict[str, Any]) -> str:
    qn = locale.get("query_normalization") or {}
    text = raw or ""
    if qn.get("nfc", True) or locale.get("accent_normalization", True):
        text = unicodedata.normalize("NFC", text)
    if qn.get("lowercase", True):
        text = text.lower()

    acronyms = locale.get("acronyms") or {}
    if isinstance(acronyms, dict):
        for key, expansion in acronyms.items():
            if key and expansion:
                text = text.replace(str(key).lower(), str(expansion).lower())

    if locale.get("greeklish_enabled", False):
        greeklish_map = locale.get("greeklish_map") or {}
        if isinstance(greeklish_map, dict):
            for src, dst in greeklish_map.items():
                if src and dst:
                    text = text.replace(str(src).lower(), str(dst).lower())

    return " ".join(text.split())
