from __future__ import annotations

import argparse
import sys

from apps.worker.jobs import activate_index, rollback_index
from apps.worker.jobs.deploy_index import deploy_index
from packages.core.stack.factory import build_stack, project_root
from packages.core.web_sources.service import crawl_client_web_sources


def _clients_root():
    stack = build_stack()
    return stack.config_store.get_clients_root()


def _config_loader(clients_root):
    from packages.core.config.loader import TenantConfigLoader

    return TenantConfigLoader(
        clients_root=clients_root,
        domain_packs_root=project_root() / "packages" / "domain_packs",
    )


def cmd_ingest(args: argparse.Namespace) -> int:
    from packages.core.ingestion.pipeline import ingest_client_uploads
    from packages.core.storage.ingest_runtime import prepare_firebase_ingest

    stack = build_stack()
    root = stack.config_store.get_clients_root()
    loader = _config_loader(root)
    prep = prepare_firebase_ingest(client_id=args.client_id, stack=stack)
    prep.emit()
    result = ingest_client_uploads(
        clients_root=root,
        client_id=args.client_id,
        config_loader=loader,
        version_id=args.version_id,
        storage=stack.tenant_storage,
        skip_runtime_hydration=True,
    )
    print(
        f"Ingest complete for {result.client_id}: version={result.version_id} "
        f"chunks={result.chunk_count} sources={result.source_count}"
    )
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from packages.core.eval.report import eval_job_exit_code
    from packages.core.eval.runner import run_eval

    root = _clients_root()
    report, run_dir = run_eval(
        clients_root=root,
        client_id=args.client_id,
        suite_filter=args.suite,
        llm_mode=args.llm_mode,
    )
    print(f"Eval {report.run_id}: status={report.status} deploy_eligible={report.deploy_eligible}")
    print(f"Report: {run_dir / 'eval_report.json'}")
    return eval_job_exit_code(report)


def cmd_crawl(args: argparse.Namespace) -> int:
    root = _clients_root()
    loader = _config_loader(root)
    result = crawl_client_web_sources(
        clients_root=root,
        client_id=args.client_id,
        config_loader=loader,
        source_ids=args.source_ids.split(",") if args.source_ids else None,
    )
    print(result)
    return 0


def cmd_drive_sync(args: argparse.Namespace) -> int:
    root = _clients_root()
    loader = _config_loader(root)
    from packages.core.drive_sources.service import sync_client_drive_sources

    result = sync_client_drive_sources(
        clients_root=root,
        client_id=args.client_id,
        config_loader=loader,
        source_ids=args.source_ids.split(",") if args.source_ids else None,
    )
    print(result)
    return 0


def cmd_deploy(args: argparse.Namespace) -> int:
    root = _clients_root()
    try:
        version = deploy_index(clients_root=root, client_id=args.client_id)
    except RuntimeError as exc:
        print(str(exc))
        return 1
    print(f"Deployed client {args.client_id!r} — activated version {version!r}")
    return 0


def cmd_activate(args: argparse.Namespace) -> int:
    root = _clients_root()
    try:
        active = activate_index.activate_index(clients_root=root, client_id=args.client_id)
    except (ValueError, PermissionError) as exc:
        print(str(exc))
        return 1
    print(f"Activated version {active!r} for client {args.client_id!r}")
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    root = _clients_root()
    try:
        active = rollback_index.rollback_index(clients_root=root, client_id=args.client_id)
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc))
        return 1
    print(f"Rolled back client {args.client_id!r} to version {active!r}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chatbot worker CLI (Cloud Run Jobs entrypoint).")
    sub = parser.add_subparsers(dest="command", required=True)

    job = sub.add_parser("job", help="Run a background job")
    job_sub = job.add_subparsers(dest="job_type", required=True)

    p_ingest = job_sub.add_parser("ingest")
    p_ingest.add_argument("--client-id", required=True)
    p_ingest.add_argument("--version-id", default=None)
    p_ingest.set_defaults(handler=cmd_ingest)

    p_eval = job_sub.add_parser("eval")
    p_eval.add_argument("--client-id", required=True)
    p_eval.add_argument("--suite", default="full")
    p_eval.add_argument("--llm-mode", default="live")
    p_eval.set_defaults(handler=cmd_eval)

    p_crawl = job_sub.add_parser("crawl")
    p_crawl.add_argument("--client-id", required=True)
    p_crawl.add_argument("--source-ids", default=None)
    p_crawl.set_defaults(handler=cmd_crawl)

    p_drive = job_sub.add_parser("drive-sync")
    p_drive.add_argument("--client-id", required=True)
    p_drive.add_argument("--source-ids", default=None)
    p_drive.set_defaults(handler=cmd_drive_sync)

    p_deploy = job_sub.add_parser("deploy")
    p_deploy.add_argument("--client-id", required=True)
    p_deploy.set_defaults(handler=cmd_deploy)

    p_activate = job_sub.add_parser("activate")
    p_activate.add_argument("--client-id", required=True)
    p_activate.set_defaults(handler=cmd_activate)

    p_rollback = job_sub.add_parser("rollback")
    p_rollback.add_argument("--client-id", required=True)
    p_rollback.set_defaults(handler=cmd_rollback)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.error("No handler configured.")
    code = handler(args)
    if type(code) is not int:
        handler_name = getattr(handler, "__name__", type(handler).__name__)
        raise TypeError(f"Worker handler {handler_name} must return int exit code, got {type(code).__name__}")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
