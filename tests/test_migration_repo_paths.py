from __future__ import annotations

from pathlib import Path

import pytest

from apps.worker.jobs._repo_paths import resolve_repo_path
from packages.core.stack.factory import project_root


def test_resolve_repo_path_relative_uses_project_root() -> None:
    root = project_root()
    assert resolve_repo_path("data/clients") == (root / "data/clients").resolve()
    assert resolve_repo_path("packages/config/clients/registry.yaml") == (
        root / "packages/config/clients/registry.yaml"
    ).resolve()


def test_resolve_repo_path_absolute_unchanged(tmp_path: Path) -> None:
    absolute = tmp_path / "clients"
    absolute.mkdir()
    assert resolve_repo_path(absolute) == absolute.resolve()


def test_resolve_repo_path_independent_of_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    expected = (project_root() / "data/clients").resolve()
    assert resolve_repo_path("data/clients") == expected


def test_migrate_to_gcs_cli_resolves_default_clients_root(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.worker.jobs import migrate_to_gcs as module

    captured: dict[str, Path] = {}

    def fake_migrate(*, clients_root: Path, **kwargs):
        captured["clients_root"] = clients_root
        return {"dry_run": True, "object_count": 0, "total_bytes": 0, "bucket": "b", "client_id": "default", "objects": []}

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    monkeypatch.setattr(module, "migrate_client_to_gcs", fake_migrate)
    module.main(["--client-id", "default"])
    assert captured["clients_root"] == (project_root() / "data/clients").resolve()
