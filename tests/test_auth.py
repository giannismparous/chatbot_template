from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_chat_requires_widget_key(client: TestClient) -> None:
    res = client.post(
        "/v1/chat/respond",
        json={"client_id": "tenant_a", "message": "hello"},
    )
    assert res.status_code == 401


def test_chat_resolves_widget_key(client: TestClient) -> None:
    res = client.post(
        "/v1/chat/respond",
        headers={
            "x-client-key": "wk_test_tenant_a",
            "Origin": "http://testserver",
        },
        json={"client_id": "tenant_a", "message": "hello"},
    )
    assert res.status_code == 200
    assert "tenant_a" in res.json()["answer"]


def test_chat_rejects_unknown_widget_key(client: TestClient) -> None:
    res = client.post(
        "/v1/chat/respond",
        headers={"x-client-key": "wk_unknown", "Origin": "http://testserver"},
        json={"client_id": "tenant_a", "message": "hello"},
    )
    assert res.status_code == 401


def test_chat_rejects_origin_not_allowed(client: TestClient) -> None:
    res = client.post(
        "/v1/chat/respond",
        headers={
            "x-client-key": "wk_test_tenant_a",
            "Origin": "http://evil.example",
        },
        json={"client_id": "tenant_a", "message": "hello"},
    )
    assert res.status_code == 403


def test_chat_rejects_body_client_id_mismatch(client: TestClient) -> None:
    res = client.post(
        "/v1/chat/respond",
        headers={
            "x-client-key": "wk_test_tenant_a",
            "Origin": "http://testserver",
        },
        json={"client_id": "tenant_b", "message": "hello"},
    )
    assert res.status_code == 403


def test_theme_rejects_path_client_id_mismatch(client: TestClient) -> None:
    res = client.get(
        "/v1/theme/tenant_b",
        headers={
            "x-client-key": "wk_test_tenant_a",
            "Origin": "http://testserver",
        },
    )
    assert res.status_code == 403


def test_chat_rejects_path_traversal_client_id(client: TestClient) -> None:
    res = client.post(
        "/v1/chat/respond",
        headers={"x-client-key": "wk_test_default"},
        json={"client_id": "../etc", "message": "hello"},
    )
    assert res.status_code == 400


def test_insecure_client_id_off_by_default(client: TestClient) -> None:
    res = client.post(
        "/v1/chat/respond",
        json={"client_id": "default", "message": "hello"},
    )
    assert res.status_code == 401


def test_insecure_client_id_mode_when_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch, mock_orchestrator
) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_CLIENT_ID", "true")
    from apps.api.dependencies import stack as stack_module

    stack_module.reset_stack()
    from fastapi.testclient import TestClient

    from apps.api.main import app

    client = TestClient(app)
    res = client.post(
        "/v1/chat/respond",
        json={"client_id": "default", "message": "hello"},
    )
    assert res.status_code == 200
    assert "default" in res.json()["answer"]
