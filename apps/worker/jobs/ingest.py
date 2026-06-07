from __future__ import annotations

import argparse
from pathlib import Path

from packages.core.config.loader import TenantConfigLoader
from packages.core.ingestion.pipeline import ingest_client_uploads
from packages.core.stack.factory import project_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest local uploads into a pending index version.")
    parser.add_argument("--client-id", required=True, help="Tenant client_id")
    parser.add_argument(
        "--clients-root",
        default=None,
        help="Override clients root (default: from stack / data/clients)",
    )
    parser.add_argument(
        "--version-id",
        default=None,
        help="Optional explicit version id (default: UTC timestamp)",
    )
    args = parser.parse_args()

    root = project_root()
    clients_root = Path(args.clients_root) if args.clients_root else (root / "data" / "clients")
    config_loader = TenantConfigLoader(
        clients_root=clients_root,
        domain_packs_root=root / "packages" / "domain_packs",
    )

    result = ingest_client_uploads(
        clients_root=clients_root,
        client_id=args.client_id,
        config_loader=config_loader,
        version_id=args.version_id,
    )
    print(
        f"Ingest complete for {result.client_id}: version={result.version_id} "
        f"chunks={result.chunk_count} sources={result.source_count} "
        f"(indexed={result.indexed_count} skipped={result.skipped_count} "
        f"unsupported={result.unsupported_count} failed={result.failed_count})"
    )
    print("Run activate_index to promote pending version to active.")


if __name__ == "__main__":
    main()
