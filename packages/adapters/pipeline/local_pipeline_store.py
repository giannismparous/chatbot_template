from __future__ import annotations

from packages.core.pipeline.models import PipelineRunRecord
from packages.core.ports.pipeline_store import PipelineStore
from packages.core.storage.tenant_storage import TenantStorage
from packages.core.tenant.paths import safe_client_id


def pipeline_record_key(pipeline_id: str) -> str:
    pid = (pipeline_id or "").strip()
    if not pid or ".." in pid or "/" in pid or "\\" in pid:
        raise ValueError(f"Invalid pipeline_id: {pipeline_id!r}")
    return f"pipelines/{pid}.json"


class LocalPipelineStore(PipelineStore):
    def __init__(self, *, tenant_storage: TenantStorage) -> None:
        self._storage = tenant_storage

    def create(self, record: PipelineRunRecord) -> PipelineRunRecord:
        cid = safe_client_id(record.client_id)
        self._storage.ensure_prefix(cid, "pipelines")
        self._storage.write_json(cid, pipeline_record_key(record.pipeline_id), record.to_dict())
        return record

    def update(self, record: PipelineRunRecord) -> None:
        cid = safe_client_id(record.client_id)
        self._storage.write_json(cid, pipeline_record_key(record.pipeline_id), record.to_dict())

    def get(self, client_id: str, pipeline_id: str) -> PipelineRunRecord | None:
        cid = safe_client_id(client_id)
        key = pipeline_record_key(pipeline_id)
        if not self._storage.exists(cid, key):
            return None
        return PipelineRunRecord.from_dict(self._storage.read_json(cid, key))

    def list_runs(self, client_id: str, *, limit: int = 20) -> list[PipelineRunRecord]:
        cid = safe_client_id(client_id)
        keys = self._storage.list_keys(cid, "pipelines/")
        records: list[PipelineRunRecord] = []
        for key in sorted(keys, reverse=True):
            if not key.endswith(".json"):
                continue
            records.append(PipelineRunRecord.from_dict(self._storage.read_json(cid, key)))
            if len(records) >= limit:
                break
        return records
