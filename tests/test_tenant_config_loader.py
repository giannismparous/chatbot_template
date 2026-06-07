from __future__ import annotations

from pathlib import Path

import pytest

from packages.adapters.config.tenant_prompt_policy import TenantPromptPolicyEngine
from packages.adapters.config.tenant_theme_provider import TenantThemeProvider
from packages.config.loaders import save_yaml
from packages.core.config.loader import TenantConfigLoader
from packages.core.config.models import ConfigValidationError

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"
FIXTURES = ROOT / "tests" / "fixtures" / "clients"


@pytest.fixture
def loader() -> TenantConfigLoader:
    return TenantConfigLoader(clients_root=FIXTURES, domain_packs_root=PACKS)


def test_loads_tenant_a_from_pack_only(loader: TenantConfigLoader) -> None:
    merged = loader.load("tenant_a")
    assert merged.domain_pack == "generic"
    assert merged.client["display_name"] == "Tenant A (test)"
    assert "base_system_prompt" in merged.prompt_policy
    assert merged.themes["colors"]["primary"] == "#1f4f7a"


def test_default_client_overrides_merge(loader: TenantConfigLoader) -> None:
    """Fixture default has only client.yaml; uses pack theme colors."""
    merged = loader.load("default")
    assert merged.client["display_name"] == "Default (test)"


def test_real_default_client_overrides(tmp_path: Path) -> None:
    data_clients = ROOT / "data" / "clients"
    loader = TenantConfigLoader(clients_root=data_clients, domain_packs_root=PACKS)
    merged = loader.load("default")
    assert merged.themes["colors"]["primary"] == "#0e3f70"
    assert "simasiaai" in merged.prompt_policy["base_system_prompt"].lower()
    assert merged.client["source_weights"]["google_drive"] == 1.1


def test_client_override_wins_on_theme(loader: TenantConfigLoader, tmp_path: Path) -> None:
    client_dir = FIXTURES / "tenant_b" / "config"
    theme_path = client_dir / "themes.yaml"
    save_yaml(str(theme_path), {"colors": {"primary": "#ff0000"}})
    try:
        loader.clear_cache("tenant_b")
        merged = loader.load("tenant_b")
        assert merged.themes["colors"]["primary"] == "#ff0000"
        assert merged.themes["colors"]["secondary"] == "#2f6da4"
    finally:
        if theme_path.exists():
            theme_path.unlink()
        loader.clear_cache("tenant_b")


def test_missing_client_dir_raises(loader: TenantConfigLoader) -> None:
    with pytest.raises(ConfigValidationError, match="not found"):
        loader.load("nonexistent_client")


def test_missing_client_yaml_raises(loader: TenantConfigLoader, tmp_path: Path) -> None:
    bad_root = tmp_path / "clients"
    (bad_root / "orphan" / "config").mkdir(parents=True)
    bad_loader = TenantConfigLoader(clients_root=bad_root, domain_packs_root=PACKS)
    with pytest.raises(ConfigValidationError, match="client.yaml"):
        bad_loader.load("orphan")


def test_prompt_engine_uses_merged_config(loader: TenantConfigLoader) -> None:
    engine = TenantPromptPolicyEngine(loader)
    prompt = engine.build_system_prompt("tenant_a", "hybrid_local")
    assert "helpful" in prompt.lower() or "professional" in prompt.lower()
    assert "relevant chunks" in prompt.lower()


def test_theme_provider_uses_merged_config(loader: TenantConfigLoader) -> None:
    provider = TenantThemeProvider(loader)
    theme = provider.get_theme("tenant_a")
    assert theme["theme_id"] == "generic_default"


def test_tenant_isolation_paths(loader: TenantConfigLoader) -> None:
    a = loader.get_client_config_dir("tenant_a")
    b = loader.get_client_config_dir("tenant_b")
    assert a != b
    assert a.name == "config"
    assert a.parent.name == "tenant_a"
