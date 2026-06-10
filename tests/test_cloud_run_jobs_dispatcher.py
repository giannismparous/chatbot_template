from __future__ import annotations

from packages.adapters.cloudrun.jobs_dispatcher import CloudRunJobsDispatcher


def test_execution_succeeded_reads_completed_condition() -> None:
    dispatcher = CloudRunJobsDispatcher(project="demo", region="europe-west1")
    execution = {
        "completionTime": "2026-06-09T12:00:00Z",
        "conditions": [{"type": "Completed", "state": "CONDITION_SUCCEEDED"}],
    }
    assert dispatcher.execution_terminal(execution) is True
    assert dispatcher.execution_succeeded(execution) is True


def test_execution_failed_reads_completed_condition() -> None:
    dispatcher = CloudRunJobsDispatcher(project="demo", region="europe-west1")
    execution = {
        "completionTime": "2026-06-09T12:00:00Z",
        "conditions": [{"type": "Completed", "state": "CONDITION_FAILED"}],
    }
    assert dispatcher.execution_terminal(execution) is True
    assert dispatcher.execution_succeeded(execution) is False
