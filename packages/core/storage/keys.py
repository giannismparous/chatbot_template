from __future__ import annotations

from pathlib import PurePosixPath

from packages.core.admin.upload_safety import UploadValidationError, validate_upload_relative_path
from packages.core.tenant.paths import safe_client_id

CLIENT_PREFIX = "clients"


def tenant_prefix(client_id: str) -> str:
    cid = safe_client_id(client_id)
    return f"{CLIENT_PREFIX}/{cid}"


def gcs_object_name(client_id: str, relative_key: str) -> str:
    """Full GCS object key: clients/{client_id}/{relative_key}."""
    cid = safe_client_id(client_id)
    rel = validate_relative_key(relative_key)
    return f"{CLIENT_PREFIX}/{cid}/{rel}"


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
