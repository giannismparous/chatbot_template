from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from packages.adapters.storage.gcs_file_store import GcsFileStore
from packages.core.drive_sources.manifest import load_drive_sync_manifest
from packages.core.drive_sources.paths import drive_sync_manifest_path
from packages.core.stack.factory import Stack
from packages.core.storage.drive_cache_hydrator import (
    collect_drive_cache_keys,
    hydrate_client_drive_cache,
)
from packages.core.storage.tenant_cache_hydrator import (
    hydrate_client_config,
    hydrate_client_index_state,
)
from packages.core.tenant.paths import safe_client_id

INGEST_CONFIG_KEYS = (
    "config/drive_sources.yaml",
    "config/web_sources.yaml",
    "config/source_mapping.yaml",
    "config/ingestion.yaml",
)


def resolve_app_git_sha() -> str:
    env_sha = os.getenv("APP_GIT_SHA", "").strip()
    if env_sha:
        return env_sha
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


@dataclass
class IngestPrepReport:
    profile: str
    git_sha: str
    gcs_bucket: str | None
    tenant_cache_root: str
    file_store_kind: str
    config_hydrated: int = 0
    drive_cache_hydrated: int = 0
    index_hydrated: int = 0
    drive_manifest_path: str = ""
    drive_manifest_exists: bool = False
    drive_manifest_sources: int = 0
    drive_indexable_keys: int = 0
    skipped_reason: str | None = None
    messages: list[str] = field(default_factory=list)

    def emit(self) -> None:
        for line in self.messages:
            print(line, flush=True)


def _download_keys(file_store: GcsFileStore, client_id: str, keys: list[str]) -> int:
    hydrated = 0
    for storage_key in keys:
        try:
            file_store.read_bytes(client_id, storage_key)
            hydrated += 1
        except FileNotFoundError:
            print(
                f"[ingest-prep] missing GCS blob client={client_id} key={storage_key}",
                flush=True,
            )
    return hydrated


def prepare_firebase_ingest(*, client_id: str, stack: Stack) -> IngestPrepReport:
    cid = safe_client_id(client_id)
    profile = stack.profile
    git_sha = resolve_app_git_sha()
    file_store = stack.file_store
    cache_root = file_store.get_local_clients_root() if hasattr(file_store, "get_local_clients_root") else stack.tenant_storage.clients_root()
    manifest_path = drive_sync_manifest_path(Path(cache_root), cid)

    report = IngestPrepReport(
        profile=profile,
        git_sha=git_sha,
        gcs_bucket=getattr(file_store, "bucket_name", None) if isinstance(file_store, GcsFileStore) else None,
        tenant_cache_root=str(cache_root),
        file_store_kind=type(file_store).__name__,
        drive_manifest_path=str(manifest_path),
    )
    report.messages.extend(
        [
            f"[ingest-prep] app_git_sha={git_sha}",
            f"[ingest-prep] STACK_PROFILE={os.getenv('STACK_PROFILE', 'local')}",
            f"[ingest-prep] GCS_BUCKET={os.getenv('GCS_BUCKET', '') or report.gcs_bucket or 'n/a'}",
            f"[ingest-prep] tenant_cache_root={report.tenant_cache_root}",
            f"[ingest-prep] file_store={report.file_store_kind}",
        ]
    )

    if profile != "firebase":
        report.skipped_reason = "not_firebase_profile"
        report.messages.append("[ingest-prep] hydration skipped (STACK_PROFILE != firebase)")
        return report

    if not isinstance(file_store, GcsFileStore):
        report.skipped_reason = "file_store_not_gcs"
        report.messages.append(
            f"[ingest-prep] hydration skipped (expected GcsFileStore, got {report.file_store_kind})"
        )
        return report

    report.config_hydrated = hydrate_client_config(
        client_id=cid,
        file_store=file_store,
        config_meta_store=stack.config_meta_store,
        force=True,
    )
    report.config_hydrated += _download_keys(file_store, cid, list(INGEST_CONFIG_KEYS))
    report.drive_cache_hydrated = hydrate_client_drive_cache(
        client_id=cid,
        file_store=file_store,
        force=True,
    )
    report.index_hydrated = hydrate_client_index_state(
        client_id=cid,
        file_store=file_store,
        force=False,
        include_active=True,
        include_previous=False,
    )

    report.drive_manifest_exists = manifest_path.is_file()
    manifest = load_drive_sync_manifest(Path(cache_root), cid) if report.drive_manifest_exists else None
    report.drive_manifest_sources = len(manifest.sources) if manifest else 0
    indexable_keys = collect_drive_cache_keys(file_store, cid, clients_root=Path(cache_root))
    report.drive_indexable_keys = max(0, len(indexable_keys) - 1)

    report.messages.extend(
        [
            f"[ingest-prep] hydrated config_blobs={report.config_hydrated}",
            f"[ingest-prep] hydrated drive_cache_blobs={report.drive_cache_hydrated}",
            f"[ingest-prep] hydrated index_blobs={report.index_hydrated}",
            f"[ingest-prep] drive_manifest_path={report.drive_manifest_path}",
            f"[ingest-prep] drive_manifest_exists={report.drive_manifest_exists}",
            f"[ingest-prep] drive_manifest_sources={report.drive_manifest_sources}",
            f"[ingest-prep] drive_indexable_cache_keys={report.drive_indexable_keys}",
        ]
    )
    return report


def ensure_firebase_ingest_assets_hydrated(
    *,
    client_id: str,
    stack: Stack | None = None,
    emit: bool = False,
) -> IngestPrepReport:
    if stack is None:
        from packages.core.stack.factory import build_stack

        stack = build_stack()
    report = prepare_firebase_ingest(client_id=client_id, stack=stack)
    if emit:
        report.emit()
    return report
