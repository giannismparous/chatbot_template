from __future__ import annotations

from datetime import datetime
from typing import Protocol

from packages.core.traces.models import TraceRecord


class TraceStore(Protocol):
    def save(self, record: TraceRecord) -> None: ...

    def get(self, trace_id: str, *, client_id: str | None = None) -> TraceRecord | None: ...

    def delete_older_than(
        self, cutoff: datetime, *, client_id: str | None = None
    ) -> int: ...
