from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packages.adapters.traces.sqlite_db import (
    empty_confidence_buckets,
    open_traces_db,
    parse_confidence_buckets,
)
from packages.core.ports.metrics_store import ClientMetrics
from packages.core.traces.metrics_extractor import extract_metric_deltas


class LocalSqliteMetricsStore:
    def __init__(self, sqlite_path: str | Path) -> None:
        self._sqlite_path = Path(sqlite_path)

    def record_chat(self, client_id: str, storable: dict[str, Any]) -> None:
        deltas = extract_metric_deltas(storable)
        now = datetime.now(timezone.utc).isoformat()

        with open_traces_db(self._sqlite_path) as conn:
            row = conn.execute(
                """
                SELECT total_chats, no_context, crisis, input_blocked, provider_fallback,
                       latency_ms_sum, latency_ms_count, confidence_buckets
                FROM client_metrics WHERE client_id = ?
                """,
                (client_id,),
            ).fetchone()

            buckets = empty_confidence_buckets()
            if row is not None:
                buckets = parse_confidence_buckets(row[7])
            for key, increment in deltas.confidence_buckets.items():
                if key in buckets:
                    buckets[key] += increment

            if row is None:
                conn.execute(
                    """
                    INSERT INTO client_metrics (
                        client_id, updated_at, total_chats, no_context, crisis,
                        input_blocked, provider_fallback, latency_ms_sum,
                        latency_ms_count, confidence_buckets
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        client_id,
                        now,
                        deltas.total_chats,
                        deltas.no_context,
                        deltas.crisis,
                        deltas.input_blocked,
                        deltas.provider_fallback,
                        deltas.latency_ms_sum,
                        deltas.latency_ms_count,
                        json.dumps(buckets),
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE client_metrics SET
                        updated_at = ?,
                        total_chats = total_chats + ?,
                        no_context = no_context + ?,
                        crisis = crisis + ?,
                        input_blocked = input_blocked + ?,
                        provider_fallback = provider_fallback + ?,
                        latency_ms_sum = latency_ms_sum + ?,
                        latency_ms_count = latency_ms_count + ?,
                        confidence_buckets = ?
                    WHERE client_id = ?
                    """,
                    (
                        now,
                        deltas.total_chats,
                        deltas.no_context,
                        deltas.crisis,
                        deltas.input_blocked,
                        deltas.provider_fallback,
                        deltas.latency_ms_sum,
                        deltas.latency_ms_count,
                        json.dumps(buckets),
                        client_id,
                    ),
                )
            conn.commit()

    def get_client_metrics(self, client_id: str) -> ClientMetrics:
        with open_traces_db(self._sqlite_path) as conn:
            row = conn.execute(
                """
                SELECT updated_at, total_chats, no_context, crisis, input_blocked,
                       provider_fallback, latency_ms_sum, latency_ms_count, confidence_buckets
                FROM client_metrics WHERE client_id = ?
                """,
                (client_id,),
            ).fetchone()
        if row is None:
            return ClientMetrics(
                client_id=client_id,
                updated_at=datetime.now(timezone.utc),
                confidence_buckets=empty_confidence_buckets(),
            )
        updated_at = datetime.fromisoformat(row[0])
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        return ClientMetrics(
            client_id=client_id,
            updated_at=updated_at,
            total_chats=int(row[1]),
            no_context=int(row[2]),
            crisis=int(row[3]),
            input_blocked=int(row[4]),
            provider_fallback=int(row[5]),
            latency_ms_sum=int(row[6]),
            latency_ms_count=int(row[7]),
            confidence_buckets=parse_confidence_buckets(row[8]),
        )
