from __future__ import annotations

import hashlib
import secrets
from typing import Any


def hash_widget_key(full_key: str) -> str:
    digest = hashlib.sha256(full_key.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def widget_key_prefix(full_key: str, *, visible_chars: int = 12) -> str:
    if len(full_key) <= visible_chars:
        return full_key
    return f"{full_key[:visible_chars]}..."


def generate_widget_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, public_key_hash)."""
    suffix = secrets.token_urlsafe(24)
    full = f"wk_{suffix}"
    return full, widget_key_prefix(full), hash_widget_key(full)


def widget_key_matches(entry: dict[str, Any], candidate: str) -> bool:
    stored = str(entry.get("public_key", "")).strip()
    if stored and stored == candidate:
        return True
    expected_hash = str(entry.get("public_key_hash", "")).strip()
    if expected_hash.startswith("sha256:"):
        digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        return expected_hash == f"sha256:{digest}"
    return False


def build_registry_key_entry(
    *,
    client_id: str,
    full_key: str,
    allowed_origins: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "key_id": f"{client_id}_widget_1",
        "key_prefix": widget_key_prefix(full_key),
        "public_key_hash": hash_widget_key(full_key),
        # DEV-ONLY: local stack resolves widget auth from plaintext registry entries.
        "dev_plaintext_storage": True,
        "public_key": full_key,
        "allowed_origins": list(allowed_origins or []),
    }


def sanitize_widget_key_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Strip secrets from registry widget key entries for API responses."""
    return {
        "key_id": entry.get("key_id"),
        "key_prefix": entry.get("key_prefix") or widget_key_prefix(str(entry.get("public_key", "wk_"))),
        "allowed_origins": list(entry.get("allowed_origins") or []),
    }


def sanitize_registry_client(entry: dict[str, Any]) -> dict[str, Any]:
    keys = [sanitize_widget_key_entry(k) for k in (entry.get("widget_keys") or []) if isinstance(k, dict)]
    return {
        "display_name": entry.get("display_name"),
        "widget_keys": keys,
    }
