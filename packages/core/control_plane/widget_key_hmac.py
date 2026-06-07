from __future__ import annotations

import hmac
import hashlib
import os
import secrets
from typing import Any

WIDGET_KEY_PREFIX_LEN = 12
HASH_ALG = "hmac-sha256-v1"
HASH_PREFIX = "hmac-sha256-v1:"


def widget_key_hash_secret() -> bytes:
    raw = os.getenv("WIDGET_KEY_HASH_SECRET", "").strip()
    if not raw:
        raise RuntimeError("WIDGET_KEY_HASH_SECRET is required for production widget key hashing.")
    return raw.encode("utf-8")


def compute_widget_key_hash(full_key: str, *, secret: bytes | None = None) -> str:
    key = (full_key or "").strip()
    if not key:
        raise ValueError("Empty widget key.")
    sec = secret if secret is not None else widget_key_hash_secret()
    digest = hmac.new(sec, key.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{HASH_PREFIX}{digest}"


def verify_widget_key_hash(full_key: str, stored_hash: str, *, secret: bytes | None = None) -> bool:
    candidate = (full_key or "").strip()
    expected = (stored_hash or "").strip()
    if not candidate or not expected.startswith(HASH_PREFIX):
        return False
    try:
        computed = compute_widget_key_hash(candidate, secret=secret)
    except RuntimeError:
        return False
    return hmac.compare_digest(computed, expected)


def widget_key_lookup_prefix(full_key: str, *, visible_chars: int = WIDGET_KEY_PREFIX_LEN) -> str:
    key = (full_key or "").strip()
    if len(key) <= visible_chars:
        return key
    return key[:visible_chars]


def widget_key_display_prefix(full_key: str, *, visible_chars: int = WIDGET_KEY_PREFIX_LEN) -> str:
    prefix = widget_key_lookup_prefix(full_key, visible_chars=visible_chars)
    if len(full_key) <= visible_chars:
        return prefix
    return f"{prefix}..."


def generate_widget_key() -> tuple[str, str, str]:
    """Return (full_key, lookup_prefix, hmac_hash)."""
    suffix = secrets.token_urlsafe(24)
    full = f"wk_{suffix}"
    return full, widget_key_lookup_prefix(full), compute_widget_key_hash(full)


def sanitize_widget_key_meta(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "key_id": entry.get("key_id"),
        "key_prefix": entry.get("key_prefix"),
        "allowed_origins": list(entry.get("allowed_origins") or []),
        "status": entry.get("status", "active"),
        "created_at": entry.get("created_at"),
        "revoked_at": entry.get("revoked_at"),
    }
