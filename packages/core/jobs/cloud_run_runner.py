from __future__ import annotations

import os
import uuid
from typing import Any, Callable

from packages.adapters.cloudrun.jobs_dispatcher import build_cloud_run_jobs_dispatcher
from packages.core.jobs.local_runner import LocalJobRunner
from packages.core.jobs.models import JobRecord, JobStatus, JobType, utc_now
from packages.core.storage.tenant_storage import TenantStorage
from packages.core.tenant.paths import safe_client_id


class CloudRunJobRunner(LocalJobRunner):
    """Record job status in GCS and optionally trigger Cloud Run Jobs via API."""

    def __init__(self, *, tenant_storage: TenantStorage) -> None:
        super().__init__(tenant_storage=tenant_storage)
        self._dispatcher = build_cloud_run_jobs_dispatcher()

    def _trigger_cloud_run(self, *, job_type: JobType, client_id: str, job_id: str) -> str | None:
        if self._dispatcher is None:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is required for Cloud Run jobs.")
        return self._dispatcher.dispatch(job_type=job_type, client_id=client_id, job_id=job_id)

    def submit(
        self,
        *,
        client_id: str,
        job_type: JobType,
        runner: Callable[[], dict[str, Any]],
    ) -> JobRecord:
        disabled = os.getenv("CLOUD_RUN_JOBS_DISABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if disabled:
            return super().submit(client_id=client_id, job_type=job_type, runner=runner)

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
            execution = self._trigger_cloud_run(job_type=job_type, client_id=cid, job_id=job_id)
            if execution:
                record.result = {"cloud_run_execution": execution}
                self._write(record)
        except Exception:
            if self._sync_mode():
                raise
        return record
