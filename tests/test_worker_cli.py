from __future__ import annotations

import argparse
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apps.worker.cli import cmd_deploy, cmd_eval
from packages.core.eval.models import EvalReport
from packages.core.eval.report import eval_job_exit_code


def _report(*, status: str = "pass", deploy_eligible: bool = True) -> EvalReport:
    return EvalReport(
        run_id="eval_test",
        client_id="default",
        status=status,  # type: ignore[arg-type]
        evaluated_index_version="v1",
        evaluated_at="2026-06-08T00:00:00Z",
        categories={},
        regulated_mode=False,
        citation_tests_required=False,
        citation_tests_present=False,
        citation_tests_passed=False,
        deploy_eligible=deploy_eligible,
        report_path="/tmp/eval_report.json",
    )


def test_eval_job_exit_code_pass_deploy_eligible() -> None:
    assert eval_job_exit_code(_report(status="pass", deploy_eligible=True)) == 0


@pytest.mark.parametrize(
    ("status", "deploy_eligible"),
    [
        ("fail", True),
        ("pass", False),
        ("fail", False),
    ],
)
def test_eval_job_exit_code_nonzero(status: str, deploy_eligible: bool) -> None:
    assert eval_job_exit_code(_report(status=status, deploy_eligible=deploy_eligible)) == 1


def test_cmd_eval_returns_zero_when_pass_and_deploy_eligible() -> None:
    report = _report(status="pass", deploy_eligible=True)
    run_dir = Path("/tmp/eval_run")
    args = argparse.Namespace(client_id="default", suite="full", llm_mode="live")

    with (
        patch("apps.worker.cli._clients_root", return_value=Path("/tmp/clients")),
        patch("packages.core.eval.runner.run_eval", return_value=(report, run_dir)),
    ):
        assert cmd_eval(args) == 0


def test_cmd_eval_returns_nonzero_when_eval_fails() -> None:
    report = _report(status="fail", deploy_eligible=False)
    run_dir = Path("/tmp/eval_run")
    args = argparse.Namespace(client_id="default", suite="full", llm_mode="live")

    with (
        patch("apps.worker.cli._clients_root", return_value=Path("/tmp/clients")),
        patch("packages.core.eval.runner.run_eval", return_value=(report, run_dir)),
    ):
        assert cmd_eval(args) == 1


def test_cmd_eval_returns_nonzero_when_not_deploy_eligible() -> None:
    report = _report(status="pass", deploy_eligible=False)
    run_dir = Path("/tmp/eval_run")
    args = argparse.Namespace(client_id="default", suite="full", llm_mode="live")

    with (
        patch("apps.worker.cli._clients_root", return_value=Path("/tmp/clients")),
        patch("packages.core.eval.runner.run_eval", return_value=(report, run_dir)),
    ):
        assert cmd_eval(args) == 1


def test_deploy_index_import_is_callable_function() -> None:
    from apps.worker import cli as worker_cli

    assert callable(worker_cli.deploy_index)
    assert not inspect.ismodule(worker_cli.deploy_index)


def test_cmd_deploy_returns_zero_on_success() -> None:
    args = argparse.Namespace(client_id="default")

    with (
        patch("apps.worker.cli._clients_root", return_value=Path("/tmp/clients")),
        patch("apps.worker.cli.deploy_index", return_value="2026-06-07T232651_0000") as deploy_mock,
    ):
        assert cmd_deploy(args) == 0
        deploy_mock.assert_called_once_with(
            clients_root=Path("/tmp/clients"),
            client_id="default",
        )


def test_cmd_deploy_returns_nonzero_on_gate_failure() -> None:
    args = argparse.Namespace(client_id="default")

    with (
        patch("apps.worker.cli._clients_root", return_value=Path("/tmp/clients")),
        patch(
            "apps.worker.cli.deploy_index",
            side_effect=RuntimeError("Deploy gate blocked (eval_failed): report failed"),
        ),
    ):
        assert cmd_deploy(args) == 1


def test_main_rejects_non_int_handler_return() -> None:
    from apps.worker import cli as worker_cli

    args = argparse.Namespace(client_id="default", suite="full", llm_mode="live")

    with (
        patch.object(worker_cli, "build_parser") as build_parser,
        patch.object(worker_cli, "cmd_eval", return_value=True),
    ):
        parser = MagicMock()
        parser.parse_args.return_value = args
        args.handler = worker_cli.cmd_eval
        build_parser.return_value = parser
        with pytest.raises(TypeError, match="must return int exit code"):
            worker_cli.main(["job", "eval", "--client-id", "default"])
