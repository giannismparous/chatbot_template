from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from packages.adapters.storage.gcs_file_store import GcsFileStore
from packages.adapters.storage.in_memory_file_store import InMemoryFileStore
from packages.adapters.storage.local_file_store import LocalFileStore
from packages.core.admin.upload_safety import UploadValidationError
from packages.core.stack.factory import build_stack, validate_stack_security


def test_local_file_store_roundtrip(tmp_path):
    root = tmp_path / "clients"
    store = LocalFileStore(root)
    store.write_text("tenant_a", "uploads/doc.txt", "hello")
    assert store.read_text("tenant_a", "uploads/doc.txt") == "hello"
    assert store.exists("tenant_a", "uploads/doc.txt")
    listed = store.list_prefix("tenant_a", "uploads/")
    assert any(item.key == "uploads/doc.txt" for item in listed)
    store.delete("tenant_a", "uploads/doc.txt")
    assert not store.exists("tenant_a", "uploads/doc.txt")


def test_local_file_store_rejects_traversal(tmp_path):
    store = LocalFileStore(tmp_path / "clients")
    with pytest.raises(UploadValidationError):
        store.read_bytes("tenant_a", "../secrets.env")


def test_in_memory_file_store_prefix_list():
    store = InMemoryFileStore()
    store.write_text("tenant_a", "jobs/job_1.json", "{}")
    store.write_text("tenant_a", "jobs/job_2.json", "{}")
    keys = [item.key for item in store.list_prefix("tenant_a", "jobs/")]
    assert keys == ["jobs/job_1.json", "jobs/job_2.json"]


def test_gcs_file_store_mocked_upload_download(tmp_path):
    bucket = MagicMock()
    blob = MagicMock()
    blob.exists.return_value = True
    blob.download_as_text.return_value = "payload"
    bucket.blob.return_value = blob
    client = MagicMock()
    client.bucket.return_value = bucket

    store = GcsFileStore(bucket_name="simasia-chatbot-prod-test", cache_root=tmp_path / "cache", client=client)
    store.write_bytes("tenant_a", "uploads/a.txt", b"abc", content_type="text/plain")
    bucket.blob.assert_called()
    blob.upload_from_string.assert_called_with(b"abc", content_type="text/plain")

    blob.exists.return_value = True
    data = store.read_bytes("tenant_a", "uploads/a.txt")
    assert data == b"abc"


def test_firebase_stack_validation_requires_admin_token(monkeypatch):
    monkeypatch.setenv("STACK_PROFILE", "firebase")
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    with pytest.raises(RuntimeError, match="ADMIN_API_TOKEN"):
        validate_stack_security("firebase")


def test_firebase_stack_validation_requires_project(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "secret")
    monkeypatch.setenv("FIRESTORE_CONTROL_PLANE", "false")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCS_BUCKET", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
        validate_stack_security("firebase")


def test_local_stack_builds_file_store():
    stack = build_stack("local")
    assert stack.profile == "local"
    assert stack.file_store is not None
    assert stack.tenant_storage.profile == "local"
