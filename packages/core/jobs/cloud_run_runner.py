from __future__ import annotations

import os
import uuid
from typing import Any, Callable

from packages.core.jobs.local_runner import LocalJobRunner
from packages.core.jobs.models import JobRecord, JobStatus, JobType, utc_now
from packages.core.storage.tenant_storage import TenantStorage
from packages.core.tenant.paths import safe_client_id


class CloudRunJobRunner(LocalJobRunner):
    """Record job status in GCS and optionally trigger Cloud Run Jobs execution."""

    def __init__(self, *, tenant_storage: TenantStorage) -> None:
        super().__init__(tenant_storage=tenant_storage)
        self._region = os.getenv("CLOUD_RUN_REGION", "europe-west1").strip()
        self._project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        self._job_prefix = os.getenv("CLOUD_RUN_JOB_PREFIX", "chatbot").strip()

    def _job_name(self, job_type: JobType) -> str:
        return f"{self._job_prefix}-{job_type.value.replace('_', '-')}"

    def _trigger_cloud_run(self, *, job_type: JobType, client_id: str, job_id: str) -> None:
        if not self._project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is required for Cloud Run jobs.")
        use_gcloud = os.getenv("CLOUD_RUN_JOBS_USE_GCLOUD", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not use_gcloud:
            return
        import subprocess

        job_name = self._job_name(job_type)
        args = [
            "gcloud",
            "run",
            "jobs",
            "execute",
            job_name,
            f"--region={self._region}",
            f"--project={self._project}",
            "--quiet",
            f"--update-env-vars=JOB_TYPE={job_type.value},CLIENT_ID={client_id},JOB_ID={job_id}",
        ]
        subprocess.run(args, check=True)

    def submit(
        self,
        *,
        client_id: str,
        job_type: JobType,
        runner: Callable[[], dict[str, Any]],
    ) -> JobRecord:
        _ = runner
        cid = safe_client_id(client_id)
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        now = utc_now()
        record = JobRecord(
            job_id=job_id,
            client_id=cid,
            job_type=job_type,
            status=JobStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        self._storage.ensure_prefix(cid, "jobs")
        self._write(record)
        try:
            self._trigger_cloud_run(job_type=job_type, client_id=cid, job_id=job_id)
        except Exception:
            if self._sync_mode():
                raise
        return record
