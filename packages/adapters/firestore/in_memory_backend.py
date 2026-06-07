from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from packages.core.control_plane.models import WidgetKeyRecord
from packages.core.jobs.models import JobRecord, JobStatus, JobType, utc_now
from packages.core.tenant.paths import safe_client_id


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(str(value))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class InMemoryFirestoreBackend:
    """Dict-backed Firestore substitute for unit tests."""

    def __init__(self) -> None:
        self.clients: dict[str, dict[str, Any]] = {}
        self.widget_keys: dict[tuple[str, str], dict[str, Any]] = {}
        self.config_meta: dict[tuple[str, str], dict[str, Any]] = {}
        self.jobs: dict[tuple[str, str], dict[str, Any]] = {}

    def upsert_client(self, client_id: str, data: dict[str, Any]) -> None:
        cid = safe_client_id(client_id)
        self.clients[cid] = deepcopy(data)

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        cid = safe_client_id(client_id)
        doc = self.clients.get(cid)
        return deepcopy(doc) if doc else None

    def list_client_ids(self) -> list[str]:
        return sorted(self.clients.keys())

    def upsert_widget_key(self, client_id: str, key_id: str, data: dict[str, Any]) -> None:
        cid = safe_client_id(client_id)
        self.widget_keys[(cid, key_id)] = deepcopy(data)

    def get_widget_key(self, client_id: str, key_id: str) -> dict[str, Any] | None:
        cid = safe_client_id(client_id)
        doc = self.widget_keys.get((cid, key_id))
        return deepcopy(doc) if doc else None

    def list_widget_keys(self, client_id: str) -> list[dict[str, Any]]:
        cid = safe_client_id(client_id)
        return [
            deepcopy(doc)
            for (stored_cid, _), doc in self.widget_keys.items()
            if stored_cid == cid
        ]

    def query_widget_keys_by_prefix(self, prefix: str, *, status: str = "active") -> list[WidgetKeyRecord]:
        out: list[WidgetKeyRecord] = []
        for (client_id, _), doc in self.widget_keys.items():
            if doc.get("status") != status:
                continue
            if doc.get("key_prefix") != prefix:
                continue
            out.append(WidgetKeyRecord.from_dict(doc, client_id=client_id))
        return out

    def upsert_config_meta(self, client_id: str, config_key: str, data: dict[str, Any]) -> None:
        cid = safe_client_id(client_id)
        self.config_meta[(cid, config_key)] = deepcopy(data)

    def get_config_meta(self, client_id: str, config_key: str) -> dict[str, Any] | None:
        cid = safe_client_id(client_id)
        doc = self.config_meta.get((cid, config_key))
        return deepcopy(doc) if doc else None

    def list_config_meta(self, client_id: str) -> list[dict[str, Any]]:
        cid = safe_client_id(client_id)
        return [
            deepcopy(doc)
            for (stored_cid, _), doc in self.config_meta.items()
            if stored_cid == cid
        ]

    def upsert_job(self, client_id: str, job_id: str, data: dict[str, Any]) -> None:
        cid = safe_client_id(client_id)
        self.jobs[(cid, job_id)] = deepcopy(data)

    def get_job(self, client_id: str, job_id: str) -> dict[str, Any] | None:
        cid = safe_client_id(client_id)
        doc = self.jobs.get((cid, job_id))
        return deepcopy(doc) if doc else None

    def list_jobs(self, client_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        cid = safe_client_id(client_id)
        records = [
            deepcopy(doc)
            for (stored_cid, _), doc in self.jobs.items()
            if stored_cid == cid
        ]
        records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return records[:limit]

    def job_record_from_dict(self, data: dict[str, Any]) -> JobRecord:
        return JobRecord.from_dict(data)

    @staticmethod
    def new_job_record(client_id: str, job_type: JobType) -> JobRecord:
        import uuid

        now = utc_now()
        return JobRecord(
            job_id=f"job_{uuid.uuid4().hex[:12]}",
            client_id=safe_client_id(client_id),
            job_type=job_type,
            status=JobStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
