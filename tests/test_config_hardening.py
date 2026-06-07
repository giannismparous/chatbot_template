from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packages.config.loaders import save_yaml
from packages.core.config.loader import TenantConfigLoader
from packages.core.config.models import ConfigValidationError
from packages.core.tenant.paths import domain_pack_dir

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"
FIXTURES = ROOT / "tests" / "fixtures" / "clients"


def test_domain_pack_dir_blocks_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Invalid client_id"):
        domain_pack_dir(tmp_path / "packs", "../outside")


def test_loader_rejects_bad_domain_pack_in_client_yaml(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    config_dir = clients_root / "evil" / "config"
    config_dir.mkdir(parents=True)
    save_yaml(
        str(config_dir / "client.yaml"),
        {"client_id": "evil", "display_name": "Evil", "domain_pack": "../../etc"},
    )
    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    with pytest.raises(ConfigValidationError, match="Invalid client_id"):
        loader.load("evil")


def test_chat_returns_503_when_config_missing(client: TestClient) -> None:
    res = client.post(
        "/v1/chat/respond",
        headers={"x-client-key": "wk_test_tenant_a", "Origin": "http://testserver"},
        json={"client_id": "missing_tenant", "message": "hi"},
    )
    assert res.status_code == 403


def test_chat_returns_503_for_unconfigured_registry_client(
    monkeypatch: pytest.MonkeyPatch, mock_orchestrator
) -> None:
    registry_path = FIXTURES.parent / "registry_missing.yaml"
    save_yaml(
        str(registry_path),
        {
            "clients": {
                "orphan": {
                    "display_name": "Orphan",
                    "widget_keys": [
                        {
                            "public_key": "wk_orphan",
                            "allowed_origins": ["http://testserver"],
                        }
                    ],
                }
            }
        },
    )
    monkeypatch.setenv("CLIENT_REGISTRY_PATH", str(registry_path))
    from apps.api.dependencies import container as container_module
    from apps.api.dependencies import stack as stack_module

    stack_module.reset_stack()
    container_module.reload_runtime()
    from fastapi.testclient import TestClient

    from apps.api.main import app

    c = TestClient(app)
    res = c.post(
        "/v1/chat/respond",
        headers={"x-client-key": "wk_orphan", "Origin": "http://testserver"},
        json={"client_id": "orphan", "message": "hi"},
    )
    assert res.status_code == 503
    assert "not found" in res.json()["detail"].lower()
    registry_path.unlink(missing_ok=True)


def test_theme_returns_503_for_missing_config(
    monkeypatch: pytest.MonkeyPatch, mock_orchestrator
) -> None:
    registry_path = FIXTURES.parent / "registry_orphan2.yaml"
    save_yaml(
        str(registry_path),
        {
            "clients": {
                "orphan2": {
                    "widget_keys": [
                        {"public_key": "wk_orphan2", "allowed_origins": ["http://testserver"]}
                    ],
                }
            }
        },
    )
    monkeypatch.setenv("CLIENT_REGISTRY_PATH", str(registry_path))
    from apps.api.dependencies import container as container_module
    from apps.api.dependencies import stack as stack_module

    stack_module.reset_stack()
    container_module.reload_runtime()
    from fastapi.testclient import TestClient

    from apps.api.main import app

    c = TestClient(app)
    res = c.get(
        "/v1/theme/orphan2",
        headers={"x-client-key": "wk_orphan2", "Origin": "http://testserver"},
    )
    assert res.status_code == 503
    registry_path.unlink(missing_ok=True)


def test_loader_invalid_client_id_is_config_error() -> None:
    loader = TenantConfigLoader(clients_root=FIXTURES, domain_packs_root=PACKS)
    with pytest.raises(ConfigValidationError, match="Invalid client_id"):
        loader.load("../etc")
