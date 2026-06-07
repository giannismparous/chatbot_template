from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apps.api.dependencies.stack import get_stack
from packages.adapters.traces.sqlite_db import open_traces_db, traces_db_path
from packages.core.config.loader import TenantConfigLoader
from packages.core.stack.factory import project_root


def _client_ids(clients_root: Path, registry_path: Path, explicit: str | None) -> list[str]:
    if explicit:
        return [explicit]
    stack = get_stack()
    registry = stack.config_store.load_registry()
    clients = registry.get("clients") or {}
    return sorted(clients.keys())


def cleanup_traces(
    *,
    client_id: str | None = None,
    dry_run: bool = False,
    as_of: datetime | None = None,
    db_path: Path | None = None,
) -> dict[str, int]:
    stack = get_stack()
    clients_root = stack.config_store.get_clients_root()
    loader = TenantConfigLoader(
        clients_root=clients_root,
        domain_packs_root=project_root() / "packages" / "domain_packs",
    )
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    path = db_path or traces_db_path()
    deleted_by_client: dict[str, int] = {}

    for cid in _client_ids(clients_root, stack.config_store.get_registry_path(), client_id):
        merged = loader.load(cid)
        retention_days = int((merged.privacy or {}).get("retention_days", 30))
        cutoff = now - timedelta(days=retention_days)
        if dry_run:
            with open_traces_db(path) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM trace_records WHERE client_id = ? AND created_at < ?",
                    (cid, cutoff.isoformat()),
                ).fetchone()
            deleted_by_client[cid] = int(row[0] if row else 0)
            continue
        deleted_by_client[cid] = stack.trace_store.delete_older_than(cutoff, client_id=cid)

    return deleted_by_client


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete expired privacy-gated trace records.")
    parser.add_argument("--client-id", default=None, help="Limit cleanup to one client")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without deleting")
    parser.add_argument(
        "--as-of",
        default=None,
        help="ISO timestamp treated as now (for tests)",
    )
    args = parser.parse_args()

    as_of = None
    if args.as_of:
        as_of = datetime.fromisoformat(args.as_of)
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)

    results = cleanup_traces(client_id=args.client_id, dry_run=args.dry_run, as_of=as_of)
    for cid, count in results.items():
        action = "would delete" if args.dry_run else "deleted"
        print(f"{cid}: {action} {count} trace(s)")


if __name__ == "__main__":
    main()
