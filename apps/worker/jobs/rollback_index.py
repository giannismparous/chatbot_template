from __future__ import annotations

import argparse
from pathlib import Path

from packages.core.ingestion.manifest import read_active_manifest, rollback_active_version
from packages.core.ingestion.paths import (
    active_manifest_path,
    knowledge_index_path,
    source_manifest_path,
)
from packages.core.stack.factory import project_root
from packages.core.tenant.paths import safe_client_id


def rollback_index(*, clients_root: Path, client_id: str) -> str:
    cid = safe_client_id(client_id)
    manifest_path = active_manifest_path(clients_root, cid)
    before = read_active_manifest(manifest_path)
    if not before.previous:
        raise ValueError(f"No previous version for client {cid!r}")

    previous_id = before.previous
    if not knowledge_index_path(clients_root, cid, previous_id).is_file():
        raise FileNotFoundError(f"Previous knowledge_index missing for version {previous_id!r}")
    if not source_manifest_path(clients_root, cid, previous_id).is_file():
        raise FileNotFoundError(f"Previous source_manifest missing for version {previous_id!r}")

    after = rollback_active_version(manifest_path)
    if not after.active:
        raise RuntimeError("Rollback did not set active version")
    return after.active


def main() -> None:
    parser = argparse.ArgumentParser(description="Roll back active index to previous version.")
    parser.add_argument("--client-id", required=True, help="Tenant client_id")
    parser.add_argument(
        "--clients-root",
        default=None,
        help="Override clients root (default: data/clients)",
    )
    args = parser.parse_args()

    root = project_root()
    clients_root = Path(args.clients_root) if args.clients_root else (root / "data" / "clients")
    active = rollback_index(clients_root=clients_root, client_id=args.client_id)
    print(f"Rolled back client {args.client_id!r} to version {active!r}")


if __name__ == "__main__":
    main()
