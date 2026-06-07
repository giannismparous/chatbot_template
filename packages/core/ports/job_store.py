from __future__ import annotations

from abc import ABC, abstractmethod

from packages.core.jobs.models import JobRecord


class JobStore(ABC):
    @abstractmethod
    def create(self, record: JobRecord) -> JobRecord:
        raise NotImplementedError

    @abstractmethod
    def update(self, record: JobRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, client_id: str, job_id: str) -> JobRecord | None:
        raise NotImplementedError

    @abstractmethod
    def list_jobs(self, client_id: str, *, limit: int = 50) -> list[JobRecord]:
        raise NotImplementedError
