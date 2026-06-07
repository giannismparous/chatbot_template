from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


def test_admin_requires_token(client: TestClient) -> None:
    res = client.get("/v1/admin/prompt-policy")
    assert res.status_code == 401


def test_admin_accepts_valid_token(client: TestClient) -> None:
    res = client.get(
        "/v1/admin/prompt-policy",
        headers={"x-admin-token": "test-admin-token"},
    )
    assert res.status_code == 200


def test_admin_rejects_invalid_token(client: TestClient) -> None:
    res = client.get(
        "/v1/admin/prompt-policy",
        headers={"x-admin-token": "wrong-token"},
    )
    assert res.status_code == 401


def test_admin_fails_closed_when_token_env_missing(
    monkeypatch: pytest.MonkeyPatch, mock_orchestrator
) -> None:
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
    monkeypatch.setenv("ALLOW_INSECURE_ADMIN", "false")
    from apps.api.dependencies import stack as stack_module

    stack_module.reset_stack()
    from fastapi.testclient import TestClient

    from apps.api.main import app

    client = TestClient(app)
    res = client.get("/v1/admin/prompt-policy")
    assert res.status_code == 401
    res2 = client.get(
        "/v1/admin/prompt-policy",
        headers={"x-admin-token": "any-token"},
    )
    assert res2.status_code == 401


def test_admin_insecure_mode_local_only(
    monkeypatch: pytest.MonkeyPatch, mock_orchestrator
) -> None:
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
    monkeypatch.setenv("ALLOW_INSECURE_ADMIN", "true")
    monkeypatch.setenv("STACK_PROFILE", "local")
    from apps.api.dependencies import stack as stack_module

    stack_module.reset_stack()
    from fastapi.testclient import TestClient

    from apps.api.main import app

    client = TestClient(app)
    res = client.get("/v1/admin/prompt-policy")
    assert res.status_code == 200


def test_admin_insecure_mode_rejected_for_firebase_profile(
    monkeypatch: pytest.MonkeyPatch, mock_orchestrator
) -> None:
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-admin-token")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("ALLOW_INSECURE_ADMIN", "true")
    monkeypatch.setenv("STACK_PROFILE", "firebase")
    from apps.api.dependencies import stack as stack_module

    stack_module.reset_stack()
    from packages.core.stack.factory import build_stack

    with pytest.raises(RuntimeError, match="ALLOW_INSECURE_ADMIN"):
        build_stack("firebase")


def test_firebase_stack_fails_startup_without_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STACK_PROFILE", "firebase")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
    from apps.api.dependencies import stack as stack_module

    stack_module.reset_stack()
    from packages.core.stack.factory import build_stack

    with pytest.raises(RuntimeError, match="ADMIN_API_TOKEN"):
        build_stack("firebase")
