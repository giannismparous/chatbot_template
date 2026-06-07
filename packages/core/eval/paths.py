from __future__ import annotations

from pathlib import Path

from packages.core.tenant.paths import client_root, safe_client_id


def client_tests_dir(clients_root: Path, client_id: str) -> Path:
    return client_root(clients_root, client_id) / "tests"


def eval_cases_dir(clients_root: Path, client_id: str) -> Path:
    return client_tests_dir(clients_root, client_id) / "cases"


def eval_suite_path(clients_root: Path, client_id: str) -> Path:
    return client_tests_dir(clients_root, client_id) / "eval_suite.yaml"


def eval_output_root(clients_root: Path, client_id: str) -> Path:
    return client_tests_dir(clients_root, client_id) / "output"


def eval_run_dir(clients_root: Path, client_id: str, run_id: str) -> Path:
    return eval_output_root(clients_root, client_id) / run_id


def latest_eval_report_path(clients_root: Path, client_id: str) -> Path:
    return eval_output_root(clients_root, client_id) / "latest_eval_report.json"


def deploy_record_path(clients_root: Path, client_id: str) -> Path:
    return eval_output_root(clients_root, client_id) / "deploy_record.json"


def latest_eval_report_key() -> str:
    return "tests/output/latest_eval_report.json"


def eval_run_key(run_id: str) -> str:
    rid = (run_id or "").strip()
    if not rid or ".." in rid or "/" in rid or "\\" in rid:
        raise ValueError(f"Invalid run_id: {run_id!r}")
    return f"tests/output/{rid}/eval_report.json"


def eval_run_prefix(run_id: str) -> str:
    rid = (run_id or "").strip()
    if not rid or ".." in rid or "/" in rid or "\\" in rid:
        raise ValueError(f"Invalid run_id: {run_id!r}")
    return f"tests/output/{rid}"

