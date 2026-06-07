from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from packages.core.jobs.models import JobRecord, JobStatus, JobType, utc_now
from packages.core.ports.job_store import JobStore
from packages.core.tenant.paths import safe_client_id


class FirestoreJobRunner:
    """Job runner backed by Firestore job documents (firebase profile)."""

    def __init__(self, *, job_store: JobStore) -> None:
        self._job_store = job_store
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="firestore-job")

    @property
    def job_store(self) -> JobStore:
        return self._job_store

    def _sync_mode(self) -> bool:
        return os.getenv("ADMIN_JOBS_SYNC", "false").strip().lower() in {"1", "true", "yes", "on"}

    def get_job(self, client_id: str, job_id: str) -> JobRecord | None:
        return self._job_store.get(client_id, job_id)

    def list_jobs(self, client_id: str, *, limit: int = 50) -> list[JobRecord]:
        return self._job_store.list_jobs(client_id, limit=limit)

    def submit(
        self,
        *,
        client_id: str,
        job_type: JobType,
        runner: Callable[[], dict[str, Any]],
    ) -> JobRecord:
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
        self._job_store.create(record)

        def _execute() -> None:
            running = JobRecord(
                job_id=record.job_id,
                client_id=record.client_id,
                job_type=record.job_type,
                status=JobStatus.RUNNING,
                created_at=record.created_at,
                updated_at=utc_now(),
            )
            self._job_store.update(running)
            try:
                result = runner()
                done = JobRecord(
                    job_id=record.job_id,
                    client_id=record.client_id,
                    job_type=record.job_type,
                    status=JobStatus.SUCCEEDED,
                    created_at=record.created_at,
                    updated_at=utc_now(),
                    result=result,
                )
                self._job_store.update(done)
            except Exception as exc:
                failed = JobRecord(
                    job_id=record.job_id,
                    client_id=record.client_id,
                    job_type=record.job_type,
                    status=JobStatus.FAILED,
                    created_at=record.created_at,
                    updated_at=utc_now(),
                    error=str(exc),
                )
                self._job_store.update(failed)

        if self._sync_mode():
            _execute()
            final = self.get_job(cid, job_id)
            assert final is not None
            return final

        self._executor.submit(_execute)
        return record

    def update_job(self, record: JobRecord) -> None:
        self._job_store.update(record)
