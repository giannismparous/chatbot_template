from __future__ import annotations

import json
import logging
import mimetypes
from pathlib import Path

from packages.adapters.storage.gcs_file_store import GcsFileStore
from packages.core.eval.paths import (
    eval_run_prefix,
    latest_eval_report_key,
    latest_eval_report_path,
)
from packages.core.ports.file_store import FileStore
from packages.core.tenant.paths import client_root, safe_client_id

logger = logging.getLogger(__name__)


def _content_type_for_path(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    if path.suffix == ".json":
        return "application/json"
    if path.suffix in {".yaml", ".yml"}:
        return "application/x-yaml"
    return "application/octet-stream"


def _client_relative_key(clients_root: Path, client_id: str, path: Path) -> str:
    root = client_root(clients_root, client_id).resolve()
    resolved = path.resolve()
    if not str(resolved).startswith(str(root)):
        raise ValueError(f"Path escapes client root: {path}")
    return resolved.relative_to(root).as_posix()


def persist_eval_output_to_storage(
    *,
    client_id: str,
    file_store: FileStore,
    clients_root: Path,
    run_dir: Path,
    latest_path: Path,
) -> int:
    """Upload latest eval report pointer and the run directory to GCS (firebase mode)."""
    if not isinstance(file_store, GcsFileStore):
        return 0

    cid = safe_client_id(client_id)
    uploaded = 0
    if latest_path.is_file():
        file_store.write_bytes(
            cid,
            latest_eval_report_key(),
            latest_path.read_bytes(),
            content_type="application/json",
        )
        uploaded += 1

    if run_dir.is_dir():
        for path in sorted(run_dir.rglob("*")):
            if not path.is_file():
                continue
            relative_key = _client_relative_key(clients_root, cid, path)
            if not relative_key.startswith("tests/output/"):
                continue
            file_store.write_bytes(
                cid,
                relative_key,
                path.read_bytes(),
                content_type=_content_type_for_path(path),
            )
            uploaded += 1
    return uploaded


def _eval_report_ready(clients_root: Path, client_id: str) -> bool:
    return latest_eval_report_path(clients_root, client_id).is_file()


def _collect_eval_report_keys(file_store: GcsFileStore, client_id: str) -> list[str]:
    cid = safe_client_id(client_id)
    keys: set[str] = {latest_eval_report_key()}

    clients_root = file_store.get_local_clients_root()
    latest_local = latest_eval_report_path(clients_root, cid)
    if not latest_local.is_file():
        try:
            file_store.read_bytes(cid, latest_eval_report_key())
        except FileNotFoundError:
            return sorted(keys)

    if latest_local.is_file():
        try:
            payload = json.loads(latest_local.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}
        run_id = str(payload.get("run_id") or "").strip()
        if run_id:
            prefix = f"{eval_run_prefix(run_id)}/"
            for obj in file_store.list_prefix(cid, prefix):
                if obj.key.startswith(prefix):
                    keys.add(obj.key)

    return sorted(keys)


def hydrate_client_eval_report(
    *,
    client_id: str,
    file_store: FileStore,
    force: bool = False,
) -> int:
    """Download latest eval report (and referenced run dir) from GCS into the local cache."""
    if not isinstance(file_store, GcsFileStore):
        return 0

    cid = safe_client_id(client_id)
    clients_root = file_store.get_local_clients_root()
    if not force and _eval_report_ready(clients_root, cid):
        return 0

    keys = _collect_eval_report_keys(file_store, cid)
    hydrated = 0
    for storage_key in keys:
        try:
            file_store.read_bytes(cid, storage_key)
            hydrated += 1
        except FileNotFoundError:
            logger.warning("Eval output blob missing in GCS for client=%s key=%s", cid, storage_key)
    return hydrated


def persist_eval_output_if_firebase(
    *,
    client_id: str,
    clients_root: Path,
    run_dir: Path,
    latest_path: Path,
) -> int:
    """Persist eval output to GCS when running on firebase profile (no-op locally)."""
    import os

    if os.getenv("STACK_PROFILE", "local").strip() != "firebase":
        return 0
    from packages.core.stack.factory import build_stack

    stack = build_stack()
    if not isinstance(stack.file_store, GcsFileStore):
        return 0
    count = persist_eval_output_to_storage(
        client_id=client_id,
        file_store=stack.file_store,
        clients_root=clients_root,
        run_dir=run_dir,
        latest_path=latest_path,
    )
    if count:
        logger.info("Persisted %s eval output blob(s) for client=%s", count, client_id)
    return count
