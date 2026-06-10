from __future__ import annotations

import os
from typing import Any

from packages.adapters.cloudrun.jobs_dispatcher import build_cloud_run_jobs_dispatcher
from packages.core.jobs.firestore_runner import FirestoreJobRunner
from packages.core.jobs.models import JobRecord, JobType
from packages.core.ports.job_store import JobStore


class CloudRunFirestoreJobRunner(FirestoreJobRunner):
    """Firestore job metadata + Cloud Run Jobs API dispatch (ADC)."""

    def __init__(self, *, job_store: JobStore) -> None:
        super().__init__(job_store=job_store)
        self._dispatcher = build_cloud_run_jobs_dispatcher()

    def _trigger_cloud_run(self, *, job_type: JobType, client_id: str, job_id: str) -> str | None:
        if self._dispatcher is None:
            return None
        return self._dispatcher.dispatch(job_type=job_type, client_id=client_id, job_id=job_id)

    def submit(self, *, client_id: str, job_type: JobType, runner) -> JobRecord:
        disabled = os.getenv("CLOUD_RUN_JOBS_DISABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if disabled or self._dispatcher is None:
            return super().submit(client_id=client_id, job_type=job_type, runner=runner)

        record = super().submit(client_id=client_id, job_type=job_type, runner=lambda: {})
        try:
            execution = self._trigger_cloud_run(job_type=job_type, client_id=client_id, job_id=record.job_id)
            if execution:
                updated = JobRecord(
                    job_id=record.job_id,
                    client_id=record.client_id,
                    job_type=record.job_type,
                    status=record.status,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                    result={**record.result, "cloud_run_execution": execution},
                )
                self.update_job(updated)
        except Exception:
            if self._sync_mode():
                raise
        return record
