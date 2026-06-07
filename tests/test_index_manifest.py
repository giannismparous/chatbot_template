from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.core.ingestion.manifest import (
    activate_pending_version,
    read_active_manifest,
    set_pending_version,
    write_active_manifest,
)
from packages.core.ingestion.models import ActiveManifest
from packages.core.ingestion.paths import version_dir


def test_set_pending_does_not_overwrite_active(tmp_path: Path) -> None:
    manifest_path = tmp_path / "active_manifest.json"
    write_active_manifest(manifest_path, ActiveManifest(active="live-v1"))
    set_pending_version(manifest_path, "pending-v2")

    manifest = read_active_manifest(manifest_path)
    assert manifest.active == "live-v1"
    assert manifest.pending == "pending-v2"


def test_activate_moves_pending_to_active_and_preserves_previous(tmp_path: Path) -> None:
    manifest_path = tmp_path / "active_manifest.json"
    write_active_manifest(
        manifest_path,
        ActiveManifest(active="live-v1", pending="pending-v2"),
    )

    after = activate_pending_version(manifest_path)
    assert after.active == "pending-v2"
    assert after.previous == "live-v1"
    assert after.pending is None

    on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert on_disk["active"] == "pending-v2"
    assert on_disk["previous"] == "live-v1"
    assert "pending" not in on_disk


def test_activate_without_pending_raises(tmp_path: Path) -> None:
    manifest_path = tmp_path / "active_manifest.json"
    write_active_manifest(manifest_path, ActiveManifest(active="live-v1"))
    with pytest.raises(ValueError, match="No pending version"):
        activate_pending_version(manifest_path)


def test_version_dir_rejects_traversal(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    (clients_root / "tenant_a" / "indexes" / "versions").mkdir(parents=True)
    with pytest.raises(ValueError):
        version_dir(clients_root, "tenant_a", "../escape")
