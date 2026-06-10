from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from packages.adapters.cloudrun.jobs_dispatcher import CloudRunJobsDispatcher, ExecutionOutcome
from packages.core.jobs.models import JobType


def _dispatcher() -> CloudRunJobsDispatcher:
    return CloudRunJobsDispatcher(project="demo", region="europe-west1")


def test_execution_succeeded_reads_completed_condition() -> None:
    dispatcher = _dispatcher()
    execution = {
        "completionTime": "2026-06-09T12:00:00Z",
        "conditions": [{"type": "Completed", "state": "CONDITION_SUCCEEDED"}],
    }
    assert dispatcher.execution_terminal(execution) is True
    assert dispatcher.execution_succeeded(execution) is True
    assert dispatcher.execution_outcome(execution) == ExecutionOutcome.SUCCEEDED


def test_execution_terminal_uses_task_counts() -> None:
    dispatcher = _dispatcher()
    execution = {
        "taskCount": 1,
        "succeededCount": 1,
        "failedCount": 0,
        "completionStatus": "EXECUTION_SUCCEEDED",
    }
    assert dispatcher.execution_terminal(execution) is True
    assert dispatcher.execution_outcome(execution) == ExecutionOutcome.SUCCEEDED


def test_execution_failure_detail_includes_message_and_log() -> None:
    dispatcher = _dispatcher()
    detail = dispatcher.execution_failure_detail(
        {
            "conditions": [
                {"type": "Completed", "state": "CONDITION_FAILED", "message": "container failed"},
            ],
            "logUri": "https://console.cloud.google.com/logs/viewer",
            "name": "projects/demo/locations/europe-west1/jobs/chatbot-ingest/executions/x",
        }
    )
    assert "container failed" in detail
    assert "log=" in detail
    assert "execution=" in detail


def test_execution_failed_reads_completed_condition() -> None:
    dispatcher = _dispatcher()
    execution = {
        "completionTime": "2026-06-09T12:00:00Z",
        "conditions": [{"type": "Completed", "state": "CONDITION_FAILED"}],
    }
    assert dispatcher.execution_terminal(execution) is True
    assert dispatcher.execution_succeeded(execution) is False
    assert dispatcher.execution_outcome(execution) == ExecutionOutcome.FAILED


def test_resolve_run_response_from_operation() -> None:
    dispatcher = _dispatcher()
    operation_name = "projects/demo/locations/europe-west1/operations/op-123"
    execution_name = (
        "projects/demo/locations/europe-west1/jobs/chatbot-ingest/executions/chatbot-ingest-abc"
    )
    run_response = {"name": operation_name, "done": False}
    completed_operation = {
        "name": operation_name,
        "done": True,
        "response": {
            "@type": "type.googleapis.com/google.cloud.run.v2.Execution",
            "name": execution_name,
            "completionStatus": "EXECUTION_RUNNING",
        },
    }

    with patch.object(dispatcher, "_api_get", return_value=completed_operation) as mock_get:
        with patch.object(dispatcher, "wait_for_operation", return_value=completed_operation):
            result = dispatcher.resolve_run_response(
                job_type=JobType.INGEST,
                run_response=run_response,
            )

    assert result.operation_name == operation_name
    assert result.execution_name == execution_name
    assert result.job_name == "chatbot-ingest"


def test_wait_for_execution_resolves_operation_name() -> None:
    dispatcher = _dispatcher()
    operation_name = "projects/demo/locations/europe-west1/operations/op-456"
    execution_name = (
        "projects/demo/locations/europe-west1/jobs/chatbot-ingest/executions/chatbot-ingest-mdsnd"
    )
    terminal_execution = {
        "name": execution_name,
        "completionTime": "2026-06-09T12:30:00Z",
        "completionStatus": "EXECUTION_SUCCEEDED",
        "succeededCount": 1,
        "taskCount": 1,
        "logUri": "https://logs.example/ingest",
    }
    completed_operation = {
        "name": operation_name,
        "done": True,
        "response": {"name": execution_name},
    }

    with patch.object(
        dispatcher,
        "wait_for_operation",
        return_value=completed_operation,
    ):
        with patch.object(dispatcher, "_api_get", return_value=terminal_execution):
            final = dispatcher.wait_for_execution(
                operation_name,
                timeout_seconds=60,
                poll_interval_seconds=0.01,
            )

    assert final["name"] == execution_name
    assert dispatcher.execution_outcome(final) == ExecutionOutcome.SUCCEEDED


def test_wait_for_execution_timeout() -> None:
    dispatcher = _dispatcher()
    execution_name = (
        "projects/demo/locations/europe-west1/jobs/chatbot-ingest/executions/running"
    )
    running = {"name": execution_name, "completionStatus": "EXECUTION_RUNNING", "taskCount": 1}

    with patch.object(dispatcher, "_api_get", return_value=running):
        with pytest.raises(TimeoutError):
            dispatcher.wait_for_execution(
                execution_name,
                timeout_seconds=0.01,
                poll_interval_seconds=0.01,
            )


def test_dispatch_with_meta_resolves_operation_to_execution() -> None:
    dispatcher = _dispatcher()
    operation_name = "projects/demo/locations/europe-west1/operations/op-run"
    execution_name = (
        "projects/demo/locations/europe-west1/jobs/chatbot-ingest/executions/chatbot-ingest-new"
    )
    run_response = {"name": operation_name}
    completed_operation = {
        "name": operation_name,
        "done": True,
        "response": {"name": execution_name},
    }

    with patch.object(dispatcher, "_auth_token", return_value="token"):
        with patch("urllib.request.urlopen") as mock_urlopen:
            post_response = MagicMock()
            post_response.read.return_value = json.dumps(run_response).encode("utf-8")
            post_response.__enter__ = lambda s: s
            post_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = post_response
            with patch.object(
                dispatcher,
                "wait_for_operation",
                return_value=completed_operation,
            ):
                result = dispatcher.dispatch_with_meta(
                    job_type=JobType.INGEST,
                    client_id="default",
                    job_id="job_test",
                )

    assert result.execution_name == execution_name
    assert result.operation_name == operation_name
