from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.dependencies import stack as stack_module
from packages.adapters.sessions.local_sqlite_session_store import LocalSqliteSessionStore
from packages.adapters.traces.sqlite_db import open_traces_db
from packages.config.loaders import save_yaml
from packages.core.chat.session_manager import ChatSessionManager
from packages.core.config.loader import TenantConfigLoader
from packages.core.domain.models import ChatMessage, ChatRequest, ChatResponse, PublicSource
from packages.core.privacy.config import normalize_privacy
from packages.core.sessions.follow_up_rewrite import rewrite_follow_up_query
from packages.core.sessions.models import SessionTurn, generate_session_id, validate_session_id
from packages.core.sessions.privacy import redact_for_session_storage, session_content_allowed

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
PACKS = ROOT / "packages" / "domain_packs"
ADMIN_HEADERS = {"x-admin-token": "test-admin-token"}
WIDGET_HEADERS = {"x-client-key": "wk_test_tenant_a", "Origin": "http://testserver"}


@pytest.fixture
def phase12_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mock_orchestrator):
    clients_root = tmp_path / "clients"
    shutil.copytree(FIXTURES / "clients", clients_root)
    registry_path = tmp_path / "registry.yaml"
    shutil.copy(FIXTURES / "registry.yaml", registry_path)
    db_path = tmp_path / "phase12.sqlite3"
    monkeypatch.setenv("CLIENTS_ROOT", str(clients_root))
    monkeypatch.setenv("CLIENT_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("TRACES_SQLITE_PATH", str(db_path))
    stack_module.reset_stack()
    from apps.api.main import app

    yield {
        "clients_root": clients_root,
        "db_path": db_path,
        "client": TestClient(app),
    }
    stack_module.reset_stack()


def _write_privacy(clients_root: Path, client_id: str, privacy: dict) -> None:
    config_dir = clients_root / client_id / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    save_yaml(str(config_dir / "privacy.yaml"), privacy)


def _session_manager(clients_root: Path, db_path: Path) -> ChatSessionManager:
    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    return ChatSessionManager(session_store=LocalSqliteSessionStore(db_path), config_loader=loader)


def _mock_response(**kwargs) -> ChatResponse:
    defaults = {
        "answer": "echo answer",
        "sources": [],
        "confidence": 0.8,
        "trace_id": "tr_test123",
        "session_id": "sess_test12345678",
    }
    defaults.update(kwargs)
    return ChatResponse(**defaults)


def test_v1_old_request_shape_still_works(client: TestClient) -> None:
    res = client.post(
        "/v1/chat/respond",
        headers=WIDGET_HEADERS,
        json={"client_id": "tenant_a", "message": "hello"},
    )
    assert res.status_code == 200
    body = res.json()
    assert "answer" in body
    assert isinstance(body["confidence"], float)
    assert "session_id" not in body or body.get("session_id") is None


def test_v1_optional_session_id_echoed(phase12_env, monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = generate_session_id()
    res = phase12_env["client"].post(
        "/v1/chat/respond",
        headers=WIDGET_HEADERS,
        json={"client_id": "tenant_a", "message": "hello", "session_id": session_id},
    )
    assert res.status_code == 200
    assert res.json().get("session_id") == session_id


def test_v2_auto_generates_session_id(phase12_env) -> None:
    res = phase12_env["client"].post(
        "/v2/chat/respond",
        headers=WIDGET_HEADERS,
        json={"client_id": "tenant_a", "message": "hello"},
    )
    assert res.status_code == 200
    sid = res.json().get("session_id")
    assert sid and sid.startswith("sess_")


def test_invalid_session_id_rejected(phase12_env) -> None:
    res = phase12_env["client"].post(
        "/v2/chat/respond",
        headers=WIDGET_HEADERS,
        json={"client_id": "tenant_a", "message": "hello", "session_id": "not-valid"},
    )
    assert res.status_code == 400


def test_validate_session_id_format() -> None:
    validate_session_id(generate_session_id())
    with pytest.raises(ValueError):
        validate_session_id("../sess_bad")


@pytest.mark.parametrize(
    "privacy",
    [
        {"mode": "standard", "session": {"enabled": True, "max_turns": 10, "ttl_hours": 24}},
        {
            "mode": "anonymized",
            "session": {"enabled": True},
            "identity": {"hash_user_id": True},
        },
        {"mode": "aggregate_only", "session": {"enabled": True}},
        {"mode": "do_not_log", "session": {"enabled": True}},
    ],
)
def test_session_storage_privacy_modes(phase12_env, privacy: dict) -> None:
    clients_root = phase12_env["clients_root"]
    db_path = phase12_env["db_path"]
    _write_privacy(clients_root, "tenant_a", privacy)
    mgr = _session_manager(clients_root, db_path)
    session_id = generate_session_id()
    req = ChatRequest(client_id="tenant_a", message="call 2105551234", user_id="user-1", session_id=session_id)
    prepared = mgr.prepare_v2(req)
    response = _mock_response(session_id=session_id, answer="Support is available.")
    mgr.persist_turns(prepared, response, original_message=req.message)

    store = LocalSqliteSessionStore(db_path)
    turns = store.load_turns("tenant_a", session_id, limit=10)
    assert len(turns) == 2
    user_turn = next(t for t in turns if t.role == "user")
    assistant_turn = next(t for t in turns if t.role == "assistant")
    mode = privacy["mode"]
    if mode in {"aggregate_only", "do_not_log"}:
        assert user_turn.content is None
        assert assistant_turn.content is None
    elif mode == "anonymized":
        assert user_turn.content is not None
        header = store.get_session("tenant_a", session_id)
        assert header is not None
        assert header.user_id_hash is not None
        assert header.user_id_hash != "user-1"
    else:
        assert user_turn.content is not None
        assert "[REDACTED]" in (user_turn.content or "")


def test_standard_mode_redacts_stored_content(phase12_env) -> None:
    clients_root = phase12_env["clients_root"]
    privacy = normalize_privacy({"mode": "standard", "pii": {"redaction_enabled": True}})
    stored = redact_for_session_storage("Email me at test@example.com", privacy)
    assert stored is not None
    assert "[REDACTED]" in stored


def test_max_turns_fifo(phase12_env) -> None:
    clients_root = phase12_env["clients_root"]
    db_path = phase12_env["db_path"]
    _write_privacy(clients_root, "tenant_a", {"mode": "standard", "session": {"enabled": True, "max_turns": 2}})
    mgr = _session_manager(clients_root, db_path)
    session_id = generate_session_id()
    for i in range(4):
        req = ChatRequest(client_id="tenant_a", message=f"msg {i}", session_id=session_id)
        prepared = mgr.prepare_v2(req)
        mgr.persist_turns(prepared, _mock_response(answer=f"ans {i}", session_id=session_id), original_message=req.message)
    store = LocalSqliteSessionStore(db_path)
    turns = store.load_turns("tenant_a", session_id, limit=20)
    assert len(turns) <= 4


def test_ttl_expiry(phase12_env) -> None:
    clients_root = phase12_env["clients_root"]
    db_path = phase12_env["db_path"]
    store = LocalSqliteSessionStore(db_path)
    session_id = generate_session_id()
    store.create_session(
        client_id="tenant_a",
        session_id=session_id,
        user_id_hash=None,
        privacy_mode="standard",
        ttl_hours=1,
    )
    expired = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with open_traces_db(db_path) as conn:
        conn.execute(
            "UPDATE chat_sessions SET expires_at = ? WHERE client_id = ? AND session_id = ?",
            (expired, "tenant_a", session_id),
        )
        conn.commit()
    assert store.get_session("tenant_a", session_id) is None
    assert store.delete_expired("tenant_a") >= 1


def test_follow_up_rewrite_uses_prior_context() -> None:
    history = [
        ChatMessage(role="user", content="What are your support hours?"),
        ChatMessage(role="assistant", content="Monday through Friday 9 to 5."),
    ]
    locale = {"follow_up": {"enabled": True, "max_short_chars": 12, "affirmatives": ["yes"]}}
    result = rewrite_follow_up_query("yes", history, locale, content_allowed=True)
    assert result.is_follow_up is True
    assert "support hours" in result.rewritten_query.lower()


def test_follow_up_rewrite_disabled_when_privacy_forbids_content() -> None:
    history = [ChatMessage(role="user", content="long prior question here")]
    result = rewrite_follow_up_query("yes", history, {"follow_up": {"enabled": True, "affirmatives": ["yes"]}}, content_allowed=False)
    assert result.rewrite_reason == "none"
    assert result.rewritten_query == "yes"


def test_v2_response_shape(phase12_env) -> None:
    res = phase12_env["client"].post(
        "/v2/chat/respond",
        headers=WIDGET_HEADERS,
        json={"client_id": "tenant_a", "message": "hello"},
    )
    body = res.json()
    assert "confidence" in body and isinstance(body["confidence"], dict)
    assert "level" in body["confidence"]
    assert "trace" not in body
    if body.get("sources"):
        assert "score" not in body["sources"][0]


def test_sse_stream_chunk_and_done(phase12_env) -> None:
    res = phase12_env["client"].post(
        "/v2/chat/respond",
        headers=WIDGET_HEADERS,
        json={"client_id": "tenant_a", "message": "hello", "stream": True},
    )
    assert res.status_code == 200
    assert "text/event-stream" in res.headers.get("content-type", "")
    text = res.text
    assert "event: done" in text
    assert "event: chunk" in text
    forbidden = ["prompt", "retrieval", "block_reason", "chunks", '"score"']
    for token in forbidden:
        assert token not in text


def test_crisis_stream_done_only(phase12_env, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.dependencies import container

    class _CrisisOrchestrator:
        def answer(self, request):
            return ChatResponse(
                answer="If you are in crisis, call 988.",
                sources=[],
                confidence=0.0,
                requires_human=True,
                trace_id="tr_crisis",
                session_id=request.session_id,
            )

    monkeypatch.setattr(container, "ORCHESTRATOR", _CrisisOrchestrator())
    res = phase12_env["client"].post(
        "/v2/chat/respond",
        headers=WIDGET_HEADERS,
        json={"client_id": "tenant_a", "message": "I want to hurt myself", "stream": True},
    )
    assert res.status_code == 200
    assert "event: chunk" not in res.text
    assert "event: done" in res.text


def test_admin_preview_requires_admin_token(phase12_env) -> None:
    res = phase12_env["client"].post(
        "/v1/admin/clients/tenant_a/preview",
        json={"message": "hello"},
    )
    assert res.status_code == 401


def test_widget_key_rejected_from_preview(phase12_env) -> None:
    res = phase12_env["client"].post(
        "/v1/admin/clients/tenant_a/preview",
        headers=WIDGET_HEADERS,
        json={"message": "hello"},
    )
    assert res.status_code == 401


def test_platform_admin_preview_active(phase12_env) -> None:
    res = phase12_env["client"].post(
        "/v1/admin/clients/tenant_a/preview",
        headers=ADMIN_HEADERS,
        json={"message": "hello", "index_scope": "active"},
    )
    assert res.status_code == 200
    body = res.json()
    assert "answer" in body
    assert "summary" in body
    assert "trace" not in body


def test_preview_pending_index_scope(phase12_env) -> None:
    clients_root = phase12_env["clients_root"]
    from packages.core.ingestion.manifest import set_pending_version
    from packages.core.ingestion.paths import active_manifest_path

    manifest = active_manifest_path(clients_root, "tenant_a")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    set_pending_version(manifest, "v-pending-test")
    res = phase12_env["client"].post(
        "/v1/admin/clients/tenant_a/preview",
        headers=ADMIN_HEADERS,
        json={"message": "hello", "index_scope": "pending"},
    )
    assert res.status_code == 200


def test_session_content_allowed_flag() -> None:
    assert session_content_allowed(normalize_privacy({"mode": "standard"})) is True
    assert session_content_allowed(normalize_privacy({"mode": "aggregate_only"})) is False
