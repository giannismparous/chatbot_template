from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from packages.core.eval.report import eval_job_exit_code
from packages.core.eval.runner import run_eval
from packages.core.stack.factory import project_root

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run per-client evaluation suite.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument(
        "--suite",
        default="full",
        choices=["full", "retrieval", "answer", "safety", "citation", "reviewer"],
    )
    parser.add_argument(
        "--llm-mode",
        default="live",
        choices=["live", "replay"],
        help="live=production-like orchestrator (default); replay=CI/local only",
    )
    parser.add_argument("--export", default=None, help="Comma-separated formats: csv,xlsx")
    parser.add_argument("--allow-internal-bundle", action="store_true")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument(
        "--clients-root",
        default=None,
        help="Override clients root (default: data/clients or stack config)",
    )
    args = parser.parse_args()

    root = project_root()
    clients_root = Path(args.clients_root) if args.clients_root else (root / "data" / "clients")
    export_formats = [x.strip() for x in args.export.split(",")] if args.export else None
    output_dir = Path(args.output_dir) if args.output_dir else None

    report, run_dir = run_eval(
        clients_root=clients_root,
        client_id=args.client_id,
        suite_filter=args.suite,
        llm_mode=args.llm_mode,
        output_dir=output_dir,
        export_formats=export_formats,
        allow_internal_bundle=args.allow_internal_bundle,
    )
    print(f"Eval {report.status.upper()} — run_id={report.run_id}")
    print(f"Report: {run_dir / 'eval_report.json'}")
    if report.failure_reasons:
        print("Failures:", ", ".join(report.failure_reasons))
    raise SystemExit(eval_job_exit_code(report))


if __name__ == "__main__":
    main()
