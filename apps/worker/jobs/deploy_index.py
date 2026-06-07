from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from apps.worker.jobs.activate_index import activate_index
from packages.core.config.loader import TenantConfigLoader
from packages.core.eval.gate import check_deploy_gate
from packages.core.eval.paths import deploy_record_path
from packages.core.stack.factory import project_root


def deploy_index(
    *,
    clients_root: Path,
    client_id: str,
    eval_report_path: Path | None = None,
    freshness_hours: float | None = None,
) -> str:
    config_loader = TenantConfigLoader(
        clients_root=clients_root,
        domain_packs_root=project_root() / "packages" / "domain_packs",
    )
    gate = check_deploy_gate(
        clients_root=clients_root,
        client_id=client_id,
        config_loader=config_loader,
        report_path=eval_report_path,
        freshness_hours=freshness_hours,
    )
    if not gate.allowed:
        raise RuntimeError(f"Deploy gate blocked ({gate.reason}): {gate.detail}")

    activated = activate_index(clients_root=clients_root, client_id=client_id)
    record = {
        "client_id": client_id,
        "activated_version": activated,
        "eval_run_id": gate.report.run_id if gate.report else None,
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }
    out = deploy_record_path(clients_root, client_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return activated


def main() -> None:
    parser = argparse.ArgumentParser(description="Gated deploy: activate pending index after eval pass.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--eval-report", default=None, help="Path to eval_report.json (default: latest)")
    parser.add_argument("--freshness-hours", type=float, default=None)
    parser.add_argument("--clients-root", default=None)
    args = parser.parse_args()

    root = project_root()
    clients_root = Path(args.clients_root) if args.clients_root else (root / "data" / "clients")
    report_path = Path(args.eval_report) if args.eval_report else None

    try:
        version = deploy_index(
            clients_root=clients_root,
            client_id=args.client_id,
            eval_report_path=report_path,
            freshness_hours=args.freshness_hours,
        )
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1) from exc
    print(f"Deployed client {args.client_id!r} — activated version {version!r}")


if __name__ == "__main__":
    main()
