from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

CONFIDENCE_BUCKETS = ("0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0")


@dataclass
class ClientMetrics:
    client_id: str
    updated_at: datetime
    total_chats: int = 0
    no_context: int = 0
    crisis: int = 0
    input_blocked: int = 0
    provider_fallback: int = 0
    latency_ms_sum: int = 0
    latency_ms_count: int = 0
    confidence_buckets: dict[str, int] = field(default_factory=dict)


class MetricsStore(Protocol):
    def record_chat(self, client_id: str, storable: dict[str, Any]) -> None: ...

    def get_client_metrics(self, client_id: str) -> ClientMetrics: ...
