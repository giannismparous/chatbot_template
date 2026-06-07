from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from packages.core.ingestion.manifest import read_active_manifest, write_active_manifest
from packages.core.ingestion.models import ActiveManifest
from packages.core.ingestion.paths import active_manifest_path


@dataclass
class IndexScopeInfo:
    scope: str
    version_id: str | None
    manifest_path: Path


@contextmanager
def eval_index_scope(
    clients_root: Path,
    client_id: str,
    *,
    scope: str,
) -> Iterator[IndexScopeInfo]:
    """
    For pending eval: temporarily point active manifest at pending version
    so production retrieval wiring reads the target index without changing
    retrieval module code.
    """
    manifest_path = active_manifest_path(clients_root, client_id)
    original = read_active_manifest(manifest_path)
    backup = ActiveManifest(
        active=original.active,
        pending=original.pending,
        previous=original.previous,
    )

    target_version = original.active if scope == "active" else original.pending
    if scope == "pending" and not original.pending:
        raise ValueError(f"No pending index version for client {client_id!r}")

    try:
        if scope == "pending" and original.pending:
            patched = ActiveManifest(
                active=original.pending,
                pending=original.pending,
                previous=original.previous,
            )
            write_active_manifest(manifest_path, patched)
        yield IndexScopeInfo(scope=scope, version_id=target_version, manifest_path=manifest_path)
    finally:
        write_active_manifest(manifest_path, backup)
