from __future__ import annotations

from pathlib import Path

import pytest

from apps.worker.jobs.migrate_to_gcs import _iter_local_objects, migrate_client_to_gcs
from packages.core.admin.upload_safety import UploadValidationError


def test_migrate_dry_run_counts_objects(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    tenant = clients_root / "default"
    (tenant / "uploads").mkdir(parents=True)
    (tenant / "uploads" / "a.txt").write_text("hello", encoding="utf-8")
    (tenant / "db").mkdir()
    (tenant / "db" / "chunks.sqlite3").write_bytes(b"sqlite")

    objects = _iter_local_objects(clients_root, "default")
    assert any(key == "uploads/a.txt" for key, _ in objects)
    assert all("db/" not in key for key, _ in objects)

    plan = migrate_client_to_gcs(
        clients_root=clients_root,
        client_id="default",
        bucket_name="simasia-chatbot-prod-demo",
        dry_run=True,
    )
    assert plan["object_count"] == 1
    assert plan["total_bytes"] == len("hello")


def test_migrate_rejects_invalid_client_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _iter_local_objects(tmp_path / "clients", "../bad")
