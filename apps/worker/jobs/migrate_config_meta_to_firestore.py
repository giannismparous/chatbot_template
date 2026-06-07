from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from apps.worker.jobs._repo_paths import resolve_repo_path
from packages.adapters.firestore.factory import build_firestore_stores
from packages.core.admin.config_keys import CONFIG_KEY_FILES, resolve_config_key
from packages.core.control_plane.models import ConfigMetaRecord
from packages.core.storage.tenant_storage import TenantStorage
from packages.core.tenant.paths import safe_client_id


def _iter_config_files(config_dir: Path) -> list[tuple[str, Path]]:
    items: list[tuple[str, Path]] = []
    if not config_dir.is_dir():
        return items
    filename_to_key = {filename: key for key, filename in CONFIG_KEY_FILES.items()}
    for path in sorted(config_dir.iterdir()):
        if not path.is_file():
            continue
        key = filename_to_key.get(path.name)
        if not key:
            continue
        items.append((key, path))
    return items


def migrate_config_meta_to_firestore(
    *,
    clients_root: Path,
    client_id: str,
    dry_run: bool = True,
) -> dict:
    cid = safe_client_id(client_id)
    config_dir = clients_root / cid / "config"
    files = _iter_config_files(config_dir)
    plan = {
        "dry_run": dry_run,
        "client_id": cid,
        "file_count": len(files),
        "files": [key for key, _ in files],
    }
    if dry_run:
        return plan

    _, config_meta_store, _ = build_firestore_stores()
    storage = TenantStorage.local(clients_root)
    now = datetime.now(timezone.utc)
    for config_key, path in files:
        canonical = resolve_config_key(config_key)
        text = path.read_text(encoding="utf-8")
        storage_key = f"config/{path.name}"
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        existing = config_meta_store.get_meta(cid, canonical)
        record = ConfigMetaRecord(
            client_id=cid,
            config_key=canonical,
            storage_key=storage_key,
            content_sha256=digest,
            size_bytes=len(text.encode("utf-8")),
            content_type="application/json" if path.name.endswith(".json") else "application/x-yaml",
            revision=(existing.revision + 1) if existing else 1,
            updated_at=now,
        )
        config_meta_store.put_meta(record)
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate client config files to Firestore metadata.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--clients-root", default="data/clients")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = resolve_repo_path(args.clients_root)

    plan = migrate_config_meta_to_firestore(
        clients_root=root,
        client_id=args.client_id,
        dry_run=not args.apply,
    )
    print(
        f"{'DRY RUN' if plan['dry_run'] else 'APPLY'}: client={plan['client_id']} "
        f"files={plan['file_count']}"
    )
    for key in plan["files"]:
        print(f"  {key}")


if __name__ == "__main__":
    main()
