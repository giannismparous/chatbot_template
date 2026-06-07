from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from packages.core.privacy.config import GatedTrace, PrivacyContext


@dataclass(frozen=True)
class TraceRecord:
    trace_id: str
    client_id: str
    session_id: str | None
    created_at: datetime
    privacy_mode: str
    payload: dict[str, Any]

    @classmethod
    def from_gated(cls, *, gated: GatedTrace, context: PrivacyContext) -> TraceRecord:
        from packages.core.privacy.config import GatedTrace as _GatedTrace

        if not isinstance(gated, _GatedTrace):
            raise TypeError("TraceRecord requires GatedTrace.storable_trace")
        payload = gated.storable_trace
        if not isinstance(payload, dict):
            raise TypeError("TraceRecord payload must be a dict from GatedTrace.storable_trace")
        trace_id = payload.get("trace_id")
        if not trace_id or not isinstance(trace_id, str):
            raise ValueError("GatedTrace.storable_trace must include trace_id")
        return cls(
            trace_id=trace_id,
            client_id=context.client_id,
            session_id=context.session_id,
            created_at=datetime.now(timezone.utc),
            privacy_mode=gated.privacy_mode,
            payload=copy.deepcopy(payload),
        )
