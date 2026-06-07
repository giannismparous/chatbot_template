from __future__ import annotations

from pathlib import Path

import pytest

from packages.adapters.auth.local_dev_auth import LocalDevAuthProvider
from packages.adapters.config.yaml_config_store import YamlConfigStore
from packages.core.tenant.errors import OriginNotAllowedError, WidgetKeyNotFoundError
from packages.core.tenant.paths import client_root, safe_client_id


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_safe_client_id_rejects_traversal() -> None:
    with pytest.raises(ValueError):
        safe_client_id("../etc")
    with pytest.raises(ValueError):
        safe_client_id("foo/bar")
    with pytest.raises(ValueError):
        safe_client_id("")


def test_client_root_stays_under_clients_root(tmp_path: Path) -> None:
    root = tmp_path / "clients"
    root.mkdir()
    path = client_root(root, "tenant_a")
    assert path == root / "tenant_a"


def test_client_root_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "clients"
    root.mkdir()
    # safe_client_id blocks .. before join
    with pytest.raises(ValueError):
        client_root(root, "..")


def test_widget_key_maps_to_client_id() -> None:
    store = YamlConfigStore(clients_root=FIXTURES / "data", registry_path=FIXTURES / "registry.yaml")
    auth = LocalDevAuthProvider(store)
    assert auth.resolve_widget_key("wk_test_tenant_a", "http://testserver") == "tenant_a"


def test_widget_key_unknown_raises() -> None:
    store = YamlConfigStore(clients_root=FIXTURES / "data", registry_path=FIXTURES / "registry.yaml")
    auth = LocalDevAuthProvider(store)
    with pytest.raises(WidgetKeyNotFoundError):
        auth.resolve_widget_key("wk_missing", "http://testserver")


def test_origin_enforced_when_configured() -> None:
    store = YamlConfigStore(clients_root=FIXTURES / "data", registry_path=FIXTURES / "registry.yaml")
    auth = LocalDevAuthProvider(store)
    with pytest.raises(OriginNotAllowedError):
        auth.resolve_widget_key("wk_test_tenant_a", "http://evil.example")


def test_empty_allowed_origins_permits_any_origin() -> None:
    store = YamlConfigStore(clients_root=FIXTURES / "data", registry_path=FIXTURES / "registry.yaml")
    auth = LocalDevAuthProvider(store)
    assert auth.resolve_widget_key("wk_test_default", "http://any-origin.example") == "default"
