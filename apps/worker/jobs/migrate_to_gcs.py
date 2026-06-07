from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from apps.worker.jobs._repo_paths import resolve_repo_path
from packages.adapters.storage.gcs_file_store import GcsFileStore
from packages.adapters.storage.local_file_store import LocalFileStore
from packages.core.storage.keys import gcs_object_name, validate_relative_key
from packages.core.tenant.paths import safe_client_id

SKIP_DIR_NAMES = {"db", "__pycache__", ".git"}
SKIP_EXTENSIONS = {".sqlite3", ".sqlite", ".pyc"}
PLATFORM_REGISTRY_KEY = "platform/registry.yaml"


def _should_skip(relative: Path) -> bool:
    parts = relative.parts
    if any(part in SKIP_DIR_NAMES for part in parts):
        return True
    if relative.name == ".gitkeep":
        return True
    if relative.suffix.lower() in SKIP_EXTENSIONS:
        return True
    return False


def _iter_local_objects(clients_root: Path, client_id: str) -> list[tuple[str, Path]]:
    cid = safe_client_id(client_id)
    tenant_root = clients_root / cid
    if not tenant_root.is_dir():
        raise FileNotFoundError(f"Client directory not found: {tenant_root}")
    objects: list[tuple[str, Path]] = []
    for path in sorted(tenant_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(tenant_root)
        if _should_skip(rel):
            continue
        try:
            key = validate_relative_key(rel.as_posix())
        except Exception:
            continue
        objects.append((key, path))
    return objects


def migrate_client_to_gcs(
    *,
    clients_root: Path,
    client_id: str,
    bucket_name: str,
    dry_run: bool = True,
    upload_registry: Path | None = None,
) -> dict:
    cid = safe_client_id(client_id)
    objects = _iter_local_objects(clients_root, cid)
    total_bytes = sum(path.stat().st_size for _, path in objects)
    plan = {
        "client_id": cid,
        "bucket": bucket_name,
        "object_count": len(objects),
        "total_bytes": total_bytes,
        "dry_run": dry_run,
        "objects": [gcs_object_name(cid, key) for key, _ in objects],
    }
    if dry_run:
        return plan

    gcs = GcsFileStore(bucket_name=bucket_name, cache_root=clients_root)
    local = LocalFileStore(clients_root)
    for key, path in objects:
        data = path.read_bytes()
        local.write_bytes(cid, key, data)
        gcs.write_bytes(cid, key, data)

    if upload_registry and upload_registry.is_file():
        blob = gcs._bucket().blob(PLATFORM_REGISTRY_KEY)
        blob.upload_from_filename(str(upload_registry), content_type="application/x-yaml")

    plan["uploaded"] = True
    plan["content_md5"] = hashlib.md5("".join(plan["objects"]).encode()).hexdigest()
    return plan


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Migrate local tenant data to GCS.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--clients-root", default="data/clients")
    parser.add_argument("--bucket", default=None, help="GCS bucket (default: simasia-chatbot-prod-{project})")
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run (default when --apply omitted)")
    parser.add_argument("--apply", action="store_true", help="Perform upload (default is dry-run)")
    parser.add_argument(
        "--registry",
        default="packages/config/clients/registry.yaml",
        help="Local registry YAML to upload as platform/registry.yaml",
    )
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        parser.error("Cannot use --dry-run together with --apply.")

    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    bucket = args.bucket or os.getenv("GCS_BUCKET", "").strip()
    if not bucket and project_id:
        bucket = f"simasia-chatbot-prod-{project_id}"
    if not bucket:
        raise SystemExit("Set --bucket or GCS_BUCKET or GOOGLE_CLOUD_PROJECT.")

    root = resolve_repo_path(args.clients_root)
    registry = resolve_repo_path(args.registry)

    result = migrate_client_to_gcs(
        clients_root=root,
        client_id=args.client_id,
        bucket_name=bucket,
        dry_run=not args.apply,
        upload_registry=registry if args.apply else None,
    )
    print(
        f"{'DRY RUN' if result['dry_run'] else 'UPLOAD'}: "
        f"{result['object_count']} objects, {result['total_bytes']} bytes → gs://{result['bucket']}/clients/{result['client_id']}/"
    )
    if result["dry_run"]:
        for name in result["objects"][:20]:
            print(f"  {name}")
        if len(result["objects"]) > 20:
            print(f"  ... and {len(result['objects']) - 20} more")


if __name__ == "__main__":
    main()
