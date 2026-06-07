from __future__ import annotations

import argparse
from pathlib import Path

from packages.core.config.loader import TenantConfigLoader
from packages.core.eval.gate import assert_skip_gate_allowed
from packages.core.ingestion.manifest import activate_pending_version, read_active_manifest
from packages.core.ingestion.paths import active_manifest_path
from packages.core.stack.factory import project_root
from packages.core.tenant.paths import safe_client_id


def activate_index(*, clients_root: Path, client_id: str, skip_gate: bool = False) -> str:
    cid = safe_client_id(client_id)
    if skip_gate:
        config_loader = TenantConfigLoader(
            clients_root=clients_root,
            domain_packs_root=project_root() / "packages" / "domain_packs",
        )
        assert_skip_gate_allowed(
            clients_root=clients_root,
            client_id=cid,
            config_loader=config_loader,
        )
    manifest_path = active_manifest_path(clients_root, cid)
    before = read_active_manifest(manifest_path)
    if not before.pending:
        raise ValueError(f"No pending version for client {cid!r}")
    after = activate_pending_version(manifest_path)
    if not after.active:
        raise RuntimeError("Activation did not set active version")
    return after.active


def main() -> None:
    parser = argparse.ArgumentParser(description="Activate pending index version for a client.")
    parser.add_argument("--client-id", required=True, help="Tenant client_id")
    parser.add_argument(
        "--clients-root",
        default=None,
        help="Override clients root (default: data/clients)",
    )
    parser.add_argument(
        "--skip-gate",
        action="store_true",
        help="Dev-only: bypass deploy gate (forbidden for regulated clients). Prefer deploy_index.",
    )
    args = parser.parse_args()

    root = project_root()
    clients_root = Path(args.clients_root) if args.clients_root else (root / "data" / "clients")
    try:
        active = activate_index(
            clients_root=clients_root,
            client_id=args.client_id,
            skip_gate=args.skip_gate,
        )
    except PermissionError as exc:
        print(str(exc))
        raise SystemExit(1) from exc
    manifest = read_active_manifest(active_manifest_path(clients_root, args.client_id))
    print(f"Activated version {active!r} for client {args.client_id!r}")
    if manifest.previous:
        print(f"Previous version preserved for rollback: {manifest.previous!r}")


if __name__ == "__main__":
    main()
