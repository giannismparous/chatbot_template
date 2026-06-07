from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from packages.core.ports.metrics_store import ClientMetrics
from packages.core.traces.models import TraceRecord
from packages.adapters.traces.sqlite_db import empty_confidence_buckets


class NoOpTraceStore:
    def save(self, record: TraceRecord) -> None:
        return None

    def get(self, trace_id: str, *, client_id: str | None = None) -> TraceRecord | None:
        return None

    def delete_older_than(
        self, cutoff: datetime, *, client_id: str | None = None
    ) -> int:
        return 0


class NoOpMetricsStore:
    def record_chat(self, client_id: str, storable: dict[str, Any]) -> None:
        return None

    def get_client_metrics(self, client_id: str) -> ClientMetrics:
        return ClientMetrics(
            client_id=client_id,
            updated_at=datetime.now(timezone.utc),
            confidence_buckets=empty_confidence_buckets(),
        )


NOOP_TRACE_STORE = NoOpTraceStore()
NOOP_METRICS_STORE = NoOpMetricsStore()
