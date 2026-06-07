from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packages.adapters.firestore.factory import build_firestore_stores
from packages.config.loaders import load_yaml
from packages.core.control_plane.widget_key_hmac import (
    HASH_ALG,
    compute_widget_key_hash,
    widget_key_lookup_prefix,
)
from packages.core.tenant.paths import safe_client_id


def _load_registry(source: Path) -> dict[str, Any]:
    data = load_yaml(str(source))
    return data if isinstance(data, dict) else {"clients": {}}


def migrate_registry_to_firestore(
    *,
    source_path: Path,
    dry_run: bool = True,
    hash_secret: bytes | None = None,
    backend: Any | None = None,
) -> dict[str, Any]:
    from packages.core.control_plane.widget_key_hmac import widget_key_hash_secret

    secret = hash_secret if hash_secret is not None else widget_key_hash_secret()
    registry = _load_registry(source_path)
    clients = registry.get("clients") or {}
    plan = {
        "dry_run": dry_run,
        "client_count": len(clients),
        "widget_key_count": 0,
        "clients": [],
    }
    if backend is None and not dry_run:
        registry_store, _, _ = build_firestore_stores(hash_secret=secret)
        backend = registry_store._backend  # noqa: SLF001
    elif backend is None:
        backend = None

    for client_id, entry in clients.items():
        if not isinstance(entry, dict):
            continue
        cid = safe_client_id(str(client_id))
        keys = entry.get("widget_keys") or []
        plan["widget_key_count"] += len(keys)
        plan["clients"].append({"client_id": cid, "keys": len(keys)})
        if dry_run:
            continue

        now = datetime.now(timezone.utc).isoformat()
        backend.upsert_client(
            cid,
            {
                "client_id": cid,
                "display_name": entry.get("display_name") or cid,
                "status": "active",
                "domain_pack": entry.get("domain_pack") or "generic",
                "config_revision": 0,
                "created_at": now,
                "updated_at": now,
            },
        )
        for index, key_entry in enumerate(keys, start=1):
            if not isinstance(key_entry, dict):
                continue
            plaintext = str(key_entry.get("public_key") or "").strip()
            if not plaintext:
                continue
            key_id = str(key_entry.get("key_id") or f"{cid}_widget_{index}")
            prefix = widget_key_lookup_prefix(plaintext)
            key_hash = compute_widget_key_hash(plaintext, secret=secret)
            backend.upsert_widget_key(
                cid,
                key_id,
                {
                    "key_id": key_id,
                    "key_prefix": prefix,
                    "key_hash": key_hash,
                    "hash_alg": HASH_ALG,
                    "allowed_origins": list(key_entry.get("allowed_origins") or []),
                    "status": "active",
                    "created_at": now,
                    "revoked_at": None,
                },
            )

    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate YAML/GCS registry to Firestore (hashed keys only).")
    parser.add_argument("--source", required=True, help="Path to registry.yaml")
    parser.add_argument("--apply", action="store_true", help="Write to Firestore (default dry-run)")
    args = parser.parse_args()

    if args.apply and not os.getenv("WIDGET_KEY_HASH_SECRET", "").strip():
        raise SystemExit("WIDGET_KEY_HASH_SECRET is required for --apply.")

    source = Path(args.source)
    plan = migrate_registry_to_firestore(source_path=source, dry_run=not args.apply)
    print(
        f"{'DRY RUN' if plan['dry_run'] else 'APPLY'}: "
        f"{plan['client_count']} clients, {plan['widget_key_count']} widget keys"
    )
    for item in plan["clients"]:
        print(f"  client={item['client_id']} keys={item['keys']}")


if __name__ == "__main__":
    main()
