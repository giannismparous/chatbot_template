from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from packages.core.jobs.models import JobRecord, JobStatus, JobType, utc_now
from packages.core.storage.tenant_storage import TenantStorage
from packages.core.tenant.paths import safe_client_id


def job_record_key(job_id: str) -> str:
    jid = (job_id or "").strip()
    if not jid or ".." in jid or "/" in jid or "\\" in jid:
        raise ValueError(f"Invalid job_id: {job_id!r}")
    return f"jobs/{jid}.json"


class LocalJobRunner:
    def __init__(self, *, tenant_storage: TenantStorage) -> None:
        self._storage = tenant_storage
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="admin-job")

    @property
    def tenant_storage(self) -> TenantStorage:
        return self._storage

    def _sync_mode(self) -> bool:
        return os.getenv("ADMIN_JOBS_SYNC", "false").strip().lower() in {"1", "true", "yes", "on"}

    def _write(self, record: JobRecord) -> None:
        self._storage.write_json(
            record.client_id,
            job_record_key(record.job_id),
            record.to_dict(),
        )

    def get_job(self, client_id: str, job_id: str) -> JobRecord | None:
        cid = safe_client_id(client_id)
        key = job_record_key(job_id)
        if not self._storage.exists(cid, key):
            return None
        data = self._storage.read_json(cid, key)
        return JobRecord.from_dict(data)

    def list_jobs(self, client_id: str, *, limit: int = 50) -> list[JobRecord]:
        cid = safe_client_id(client_id)
        keys = self._storage.list_keys(cid, "jobs/")
        records: list[JobRecord] = []
        for key in sorted(keys, reverse=True):
            if not key.endswith(".json"):
                continue
            data = self._storage.read_json(cid, key)
            records.append(JobRecord.from_dict(data))
            if len(records) >= limit:
                break
        return records

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
        self._storage.ensure_prefix(cid, "jobs")
        self._write(record)

        def _execute() -> None:
            running = JobRecord(
                job_id=record.job_id,
                client_id=record.client_id,
                job_type=record.job_type,
                status=JobStatus.RUNNING,
                created_at=record.created_at,
                updated_at=utc_now(),
            )
            self._write(running)
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
                self._write(done)
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
                self._write(failed)

        if self._sync_mode():
            _execute()
            final = self.get_job(cid, job_id)
            assert final is not None
            return final

        self._executor.submit(_execute)
        return record

    def update_job(self, record: JobRecord) -> None:
        self._write(record)
