from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from packages.core.ports.metrics_store import CONFIDENCE_BUCKETS

TOP_LEVEL_FLAGS = frozenset({"no_context", "crisis_hit", "input_blocked", "fallback_used"})


@dataclass
class MetricDeltas:
    total_chats: int = 1
    no_context: int = 0
    crisis: int = 0
    input_blocked: int = 0
    provider_fallback: int = 0
    latency_ms_sum: int = 0
    latency_ms_count: int = 0
    confidence_buckets: dict[str, int] = field(default_factory=dict)


def extract_metric_deltas(storable: dict[str, Any]) -> MetricDeltas:
    """Derive aggregate-safe counters from gated storable trace (allowlist only)."""
    deltas = MetricDeltas()

    for flag in TOP_LEVEL_FLAGS:
        if flag in storable and bool(storable[flag]):
            if flag == "no_context":
                deltas.no_context = 1
            elif flag == "crisis_hit":
                deltas.crisis = 1
            elif flag == "input_blocked":
                deltas.input_blocked = 1
            elif flag == "fallback_used":
                deltas.provider_fallback = 1

    llm = storable.get("llm")
    if isinstance(llm, dict) and bool(llm.get("fallback_used")):
        deltas.provider_fallback = 1

    latency = storable.get("latency_ms")
    if isinstance(latency, dict):
        total = latency.get("total")
        if isinstance(total, (int, float)) and total >= 0:
            deltas.latency_ms_sum = int(total)
            deltas.latency_ms_count = 1

    confidence = storable.get("confidence")
    if isinstance(confidence, (int, float)):
        bucket = _confidence_bucket(float(confidence))
        if bucket:
            deltas.confidence_buckets[bucket] = 1

    return deltas


def _confidence_bucket(value: float) -> str | None:
    if value < 0.0 or value > 1.0:
        return None
    edges = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    for idx, label in enumerate(CONFIDENCE_BUCKETS):
        low = edges[idx]
        high = edges[idx + 1]
        if idx == len(CONFIDENCE_BUCKETS) - 1:
            if low <= value <= high:
                return label
        elif low <= value < high:
            return label
    return None
