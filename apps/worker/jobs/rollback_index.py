from __future__ import annotations

import argparse
import logging
from pathlib import Path

from apps.worker.jobs._tenant_storage import tenant_storage_for_worker
from packages.core.ingestion.manifest import (
    read_active_manifest,
    read_active_manifest_storage,
    rollback_active_version,
    rollback_active_version_storage,
)
from packages.core.ingestion.paths import (
    ingest_report_key,
    knowledge_index_key,
    source_manifest_key,
    active_manifest_path,
)
from packages.core.stack.factory import project_root
from packages.core.storage.keys import gcs_object_name
from packages.core.tenant.paths import safe_client_id

logger = logging.getLogger(__name__)


def rollback_index(*, clients_root: Path, client_id: str) -> str:
    cid = safe_client_id(client_id)
    storage = tenant_storage_for_worker(clients_root)
    manifest_storage_key = "indexes/active_manifest.json"
    canonical_key = gcs_object_name(cid, manifest_storage_key)

    if storage.profile == "firebase":
        before = read_active_manifest_storage(storage, cid)
        if not before.previous:
            raise ValueError(f"No previous version for client {cid!r}")
        previous_id = before.previous
        if not storage.exists(cid, knowledge_index_key(previous_id)):
            raise FileNotFoundError(f"Previous knowledge_index missing for version {previous_id!r}")
        if not storage.exists(cid, source_manifest_key(previous_id)):
            raise FileNotFoundError(f"Previous source_manifest missing for version {previous_id!r}")
        logger.info(
            "Index rollback: client=%s storage_key=%s before=%s",
            cid,
            canonical_key,
            before.to_dict(),
        )
        after = rollback_active_version_storage(storage, cid)
        logger.info(
            "Index rollback: client=%s storage_key=%s after=%s",
            cid,
            canonical_key,
            after.to_dict(),
        )
    else:
        manifest_path = active_manifest_path(clients_root, cid)
        before = read_active_manifest(manifest_path)
        if not before.previous:
            raise ValueError(f"No previous version for client {cid!r}")
        previous_id = before.previous
        if not (clients_root / cid / knowledge_index_key(previous_id)).is_file():
            raise FileNotFoundError(f"Previous knowledge_index missing for version {previous_id!r}")
        if not (clients_root / cid / source_manifest_key(previous_id)).is_file():
            raise FileNotFoundError(f"Previous source_manifest missing for version {previous_id!r}")
        after = rollback_active_version(manifest_path)

    if after.active:
        if storage.profile == "firebase":
            storage.remember_active_index_version(cid, after.active)
        if storage.profile == "firebase" and not storage.exists(cid, ingest_report_key(after.active)):
            logger.warning(
                "Index rollback: ingest_report missing for client=%s version=%s",
                cid,
                after.active,
            )
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
