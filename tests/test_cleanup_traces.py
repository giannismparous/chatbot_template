from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apps.worker.jobs.cleanup_traces import cleanup_traces
from packages.adapters.traces.local_sqlite_trace_store import LocalSqliteTraceStore
from packages.adapters.traces.sqlite_db import open_traces_db
from packages.config.loaders import save_yaml
from packages.core.traces.models import TraceRecord

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"


def _seed_trace(
    db_path: Path,
    *,
    trace_id: str,
    client_id: str,
    created_at: datetime,
) -> None:
    record = TraceRecord(
        trace_id=trace_id,
        client_id=client_id,
        session_id=None,
        created_at=created_at,
        privacy_mode="standard",
        payload={"trace_id": trace_id, "privacy_mode": "standard", "mode": "hybrid_local"},
    )
    LocalSqliteTraceStore(db_path).save(record)


def _setup_clients(tmp_path: Path) -> Path:
    clients_root = tmp_path / "clients"
    registry_path = tmp_path / "registry.yaml"

    for cid, retention in (("tenant_a", 7), ("tenant_b", 30)):
        config_dir = clients_root / cid / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        save_yaml(
            str(config_dir / "client.yaml"),
            {"client_id": cid, "display_name": cid, "domain_pack": "generic"},
        )
        save_yaml(
            str(config_dir / "privacy.yaml"),
            {"mode": "standard", "storage": {"persist_traces": True}, "retention_days": retention},
        )

    save_yaml(
        str(registry_path),
        {
            "clients": {
                "tenant_a": {"display_name": "A"},
                "tenant_b": {"display_name": "B"},
            }
        },
    )
    return clients_root


def test_cleanup_deletes_old_rows_respecting_per_client_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "traces.sqlite3"
    clients_root = _setup_clients(tmp_path)
    registry_path = tmp_path / "registry.yaml"
    monkeypatch.setenv("TRACES_SQLITE_PATH", str(db_path))
    monkeypatch.setenv("CLIENTS_ROOT", str(clients_root))
    monkeypatch.setenv("CLIENT_REGISTRY_PATH", str(registry_path))

    from apps.api.dependencies import stack as stack_module

    stack_module.reset_stack()

    now = datetime(2026, 6, 6, tzinfo=timezone.utc)
    _seed_trace(db_path, trace_id="tr_old_a", client_id="tenant_a", created_at=now - timedelta(days=10))
    _seed_trace(db_path, trace_id="tr_new_a", client_id="tenant_a", created_at=now - timedelta(days=1))
    _seed_trace(db_path, trace_id="tr_old_b", client_id="tenant_b", created_at=now - timedelta(days=20))
    _seed_trace(db_path, trace_id="tr_new_b", client_id="tenant_b", created_at=now - timedelta(days=1))

    results = cleanup_traces(as_of=now, db_path=db_path)
    assert results["tenant_a"] == 1
    assert results["tenant_b"] == 0

    store = LocalSqliteTraceStore(db_path)
    assert store.get("tr_old_a") is None
    assert store.get("tr_new_a") is not None
    assert store.get("tr_old_b") is not None
    assert store.get("tr_new_b") is not None


def test_dry_run_cleanup_does_not_delete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "traces.sqlite3"
    clients_root = _setup_clients(tmp_path)
    registry_path = tmp_path / "registry.yaml"
    monkeypatch.setenv("TRACES_SQLITE_PATH", str(db_path))
    monkeypatch.setenv("CLIENTS_ROOT", str(clients_root))
    monkeypatch.setenv("CLIENT_REGISTRY_PATH", str(registry_path))

    from apps.api.dependencies import stack as stack_module

    stack_module.reset_stack()

    now = datetime(2026, 6, 6, tzinfo=timezone.utc)
    _seed_trace(db_path, trace_id="tr_old_a", client_id="tenant_a", created_at=now - timedelta(days=30))

    results = cleanup_traces(as_of=now, dry_run=True, db_path=db_path)
    assert results["tenant_a"] == 1
    assert LocalSqliteTraceStore(db_path).get("tr_old_a") is not None

    with open_traces_db(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM trace_records").fetchone()[0]
    assert int(count) == 1
