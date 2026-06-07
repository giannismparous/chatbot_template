from __future__ import annotations

from pathlib import Path

import pytest

from apps.worker.jobs.init_client import init_client

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"


def test_init_client_creates_skeleton(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    config_dir = init_client(
        "acme",
        domain_pack="generic",
        display_name="Acme Corp",
        clients_root=clients_root,
    )
    assert (config_dir / "client.yaml").is_file()
    assert (clients_root / "acme" / "uploads").is_dir()
    assert (clients_root / "acme" / "indexes" / "versions").is_dir()
    assert not (config_dir / "prompt_policy.yaml").exists()

    from packages.core.config.loader import TenantConfigLoader

    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    merged = loader.load("acme")
    assert merged.client["display_name"] == "Acme Corp"
    assert merged.prompt_policy["base_system_prompt"]


def test_init_client_refuses_existing(tmp_path: Path) -> None:
    clients_root = tmp_path / "clients"
    init_client("dup", clients_root=clients_root)
    with pytest.raises(FileExistsError):
        init_client("dup", clients_root=clients_root)
