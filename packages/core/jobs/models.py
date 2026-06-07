from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class JobType(str, Enum):
    INGEST = "ingest"
    EVAL = "eval"
    CRAWL = "crawl"
    DRIVE_SYNC = "drive_sync"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class JobRecord:
    job_id: str
    client_id: str
    job_type: JobType
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "client_id": self.client_id,
            "job_type": self.job_type.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobRecord:
        created = datetime.fromisoformat(str(data["created_at"]))
        updated = datetime.fromisoformat(str(data["updated_at"]))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return cls(
            job_id=str(data["job_id"]),
            client_id=str(data["client_id"]),
            job_type=JobType(str(data["job_type"])),
            status=JobStatus(str(data["status"])),
            created_at=created,
            updated_at=updated,
            result=dict(data.get("result") or {}),
            error=data.get("error"),
        )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
