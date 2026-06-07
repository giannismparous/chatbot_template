from __future__ import annotations

from pathlib import Path

from packages.core.tenant.paths import client_root, safe_client_id


def client_uploads_dir(clients_root: Path, client_id: str) -> Path:
    return client_root(clients_root, client_id) / "uploads"


def client_indexes_dir(clients_root: Path, client_id: str) -> Path:
    return client_root(clients_root, client_id) / "indexes"


def client_versions_dir(clients_root: Path, client_id: str) -> Path:
    return client_indexes_dir(clients_root, client_id) / "versions"


def active_manifest_path(clients_root: Path, client_id: str) -> Path:
    return client_indexes_dir(clients_root, client_id) / "active_manifest.json"


def version_dir(clients_root: Path, client_id: str, version_id: str) -> Path:
    cid = safe_client_id(client_id)
    vid = _safe_version_id(version_id)
    root = client_versions_dir(clients_root, cid).resolve()
    path = (root / vid).resolve()
    if not str(path).startswith(str(root)):
        raise ValueError(f"version_id escapes versions root: {version_id!r}")
    return path


def knowledge_index_path(clients_root: Path, client_id: str, version_id: str) -> Path:
    return version_dir(clients_root, client_id, version_id) / "knowledge_index.json"


def source_manifest_path(clients_root: Path, client_id: str, version_id: str) -> Path:
    return version_dir(clients_root, client_id, version_id) / "source_manifest.json"


def vector_index_path(clients_root: Path, client_id: str, version_id: str) -> Path:
    return version_dir(clients_root, client_id, version_id) / "vector_index.json"


def ingest_report_path(clients_root: Path, client_id: str, version_id: str) -> Path:
    return version_dir(clients_root, client_id, version_id) / "ingest_report.json"


def active_manifest_key() -> str:
    return "indexes/active_manifest.json"


def knowledge_index_key(version_id: str) -> str:
    return f"indexes/versions/{_safe_version_id(version_id)}/knowledge_index.json"


def source_manifest_key(version_id: str) -> str:
    return f"indexes/versions/{_safe_version_id(version_id)}/source_manifest.json"


def vector_index_key(version_id: str) -> str:
    return f"indexes/versions/{_safe_version_id(version_id)}/vector_index.json"


def ingest_report_key(version_id: str) -> str:
    return f"indexes/versions/{_safe_version_id(version_id)}/ingest_report.json"


def uploads_prefix() -> str:
    return "uploads"


def _safe_version_id(version_id: str) -> str:
    normalized = (version_id or "").strip()
    if not normalized or ".." in normalized or "/" in normalized or "\\" in normalized:
        raise ValueError(f"Invalid version_id: {version_id!r}")
    return normalized


def resolve_active_knowledge_index(clients_root: Path, client_id: str) -> Path | None:
    """Return path to active knowledge_index.json, or None if no active version."""
    from packages.core.ingestion.manifest import read_active_manifest

    manifest_path = active_manifest_path(clients_root, client_id)
    if not manifest_path.is_file():
        return None
    manifest = read_active_manifest(manifest_path)
    if not manifest.active:
        return None
    index_path = knowledge_index_path(clients_root, client_id, manifest.active)
    return index_path if index_path.is_file() else None
