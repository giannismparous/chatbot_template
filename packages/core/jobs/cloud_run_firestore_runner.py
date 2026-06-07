from __future__ import annotations

import os
from typing import Any

from packages.core.jobs.firestore_runner import FirestoreJobRunner
from packages.core.jobs.models import JobRecord, JobType
from packages.core.ports.job_store import JobStore


class CloudRunFirestoreJobRunner(FirestoreJobRunner):
    """Firestore job metadata + optional Cloud Run Jobs trigger."""

    def __init__(self, *, job_store: JobStore) -> None:
        super().__init__(job_store=job_store)
        self._region = os.getenv("CLOUD_RUN_REGION", "europe-west1").strip()
        self._project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        self._job_prefix = os.getenv("CLOUD_RUN_JOB_PREFIX", "chatbot").strip()

    def _job_name(self, job_type: JobType) -> str:
        return f"{self._job_prefix}-{job_type.value.replace('_', '-')}"

    def _trigger_cloud_run(self, *, job_type: JobType, client_id: str, job_id: str) -> None:
        if not self._project:
            return
        if os.getenv("CLOUD_RUN_JOBS_USE_GCLOUD", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return
        import subprocess

        subprocess.run(
            [
                "gcloud",
                "run",
                "jobs",
                "execute",
                self._job_name(job_type),
                f"--region={self._region}",
                f"--project={self._project}",
                "--quiet",
                f"--update-env-vars=JOB_TYPE={job_type.value},CLIENT_ID={client_id},JOB_ID={job_id}",
            ],
            check=True,
        )

    def submit(self, *, client_id: str, job_type: JobType, runner) -> JobRecord:
        use_gcloud = os.getenv("CLOUD_RUN_JOBS_USE_GCLOUD", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        disabled = os.getenv("CLOUD_RUN_JOBS_DISABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if disabled or not use_gcloud:
            return super().submit(client_id=client_id, job_type=job_type, runner=runner)
        record = super().submit(client_id=client_id, job_type=job_type, runner=lambda: {})
        try:
            self._trigger_cloud_run(job_type=job_type, client_id=client_id, job_id=record.job_id)
        except Exception:
            if self._sync_mode():
                raise
        return record
