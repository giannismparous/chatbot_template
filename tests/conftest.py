from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "tests" / "fixtures"
TRACES_DB = FIXTURES / "_traces_test.sqlite3"


@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STACK_PROFILE", "local")
    monkeypatch.setenv("CLIENT_REGISTRY_PATH", str(FIXTURES / "registry.yaml"))
    monkeypatch.setenv("CLIENTS_ROOT", str(FIXTURES / "clients"))
    monkeypatch.setenv("ALLOW_INSECURE_CLIENT_ID", "false")
    monkeypatch.setenv("ALLOW_INSECURE_ADMIN", "false")
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-admin-token")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    if TRACES_DB.exists():
        TRACES_DB.unlink()
    monkeypatch.setenv("TRACES_SQLITE_PATH", str(TRACES_DB))
    from apps.api.dependencies import container as container_module
    from apps.api.dependencies import stack as stack_module

    stack_module.reset_stack()
    container_module.reload_runtime()


@pytest.fixture
def mock_orchestrator(monkeypatch: pytest.MonkeyPatch):
    from packages.core.domain.models import ChatResponse, PublicSource

    class _MockOrchestrator:
        def answer(self, request):
            return ChatResponse(
                answer=f"echo:{request.client_id}:{request.message}",
                sources=[
                    PublicSource(
                        index=1,
                        title="Example",
                        url="https://example.com/doc",
                        score=0.9,
                    )
                ],
                confidence=0.9,
                requires_human=False,
                escalation=None,
                trace_id="tr_test_mock",
                trace={"client_id": request.client_id},
                session_id=request.session_id,
            )

    from apps.api.dependencies import container

    monkeypatch.setattr(container, "ORCHESTRATOR", _MockOrchestrator())
    return _MockOrchestrator()


@pytest.fixture
def client(mock_orchestrator):
    from fastapi.testclient import TestClient

    from apps.api.main import app

    return TestClient(app)
