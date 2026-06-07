from __future__ import annotations

import os
from pathlib import PurePosixPath

from packages.core.admin.upload_safety import UploadValidationError, validate_upload_relative_path
from packages.core.tenant.paths import safe_client_id

CLIENT_PREFIX = "clients"


def gcs_client_prefix() -> str:
    raw = os.getenv("GCS_CLIENT_PREFIX", CLIENT_PREFIX).strip().strip("/")
    return raw or CLIENT_PREFIX


def tenant_prefix(client_id: str) -> str:
    cid = safe_client_id(client_id)
    return f"{gcs_client_prefix()}/{cid}"


def gcs_object_name(client_id: str, relative_key: str) -> str:
    """Canonical GCS object key: {prefix}/{client_id}/{relative_key}."""
    cid = safe_client_id(client_id)
    rel = validate_relative_key(relative_key)
    return f"{gcs_client_prefix()}/{cid}/{rel}"


def gcs_object_name_candidates(client_id: str, relative_key: str) -> list[str]:
    """Canonical key first, then legacy {client_id}/{relative_key} for migrated buckets."""
    cid = safe_client_id(client_id)
    rel = validate_relative_key(relative_key)
    canonical = gcs_object_name(cid, rel)
    legacy = f"{cid}/{rel}"
    if legacy == canonical:
        return [canonical]
    return [canonical, legacy]


def gcs_list_prefixes(client_id: str, relative_prefix: str = "") -> list[str]:
    """GCS blob prefixes to scan (canonical + legacy layout)."""
    cid = safe_client_id(client_id)
    base = gcs_client_prefix()
    rel = validate_relative_key(relative_prefix) if relative_prefix else ""
    prefixes: list[str] = []
    canonical = f"{base}/{cid}/"
    if rel:
        canonical = f"{canonical}{rel}"
    prefixes.append(canonical)
    legacy = f"{cid}/"
    if rel:
        legacy = f"{legacy}{rel}"
    if legacy not in prefixes:
        prefixes.append(legacy)
    return prefixes


def validate_relative_key(relative_key: str) -> str:
    raw = (relative_key or "").strip().replace("\\", "/")
    if not raw:
        raise UploadValidationError("Missing storage key.")
    if raw.startswith("/"):
        raise UploadValidationError("Absolute storage keys are not allowed.")
    parts = PurePosixPath(raw).parts
    if ".." in parts:
        raise UploadValidationError("Path traversal is not allowed.")
    return PurePosixPath(raw).as_posix()


def validate_upload_key(relative_path: str) -> str:
    return validate_upload_relative_path(relative_path)


def join_key(*parts: str) -> str:
    cleaned = [p.strip("/").replace("\\", "/") for p in parts if p and p.strip()]
    if not cleaned:
        raise UploadValidationError("Invalid storage key.")
    return validate_relative_key("/".join(cleaned))
