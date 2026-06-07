from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from packages.adapters.traces.sqlite_db import open_traces_db
from packages.core.traces.models import TraceRecord


class LocalSqliteTraceStore:
    def __init__(self, sqlite_path: str | Path) -> None:
        self._sqlite_path = Path(sqlite_path)

    def save(self, record: TraceRecord) -> None:
        if not isinstance(record, TraceRecord):
            raise TypeError("TraceStore.save requires TraceRecord from GatedTrace.storable_trace")
        created_at = record.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        with open_traces_db(self._sqlite_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trace_records
                    (trace_id, client_id, session_id, created_at, privacy_mode, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.trace_id,
                    record.client_id,
                    record.session_id,
                    created_at.isoformat(),
                    record.privacy_mode,
                    json.dumps(record.payload, ensure_ascii=False),
                ),
            )
            conn.commit()

    def get(self, trace_id: str, *, client_id: str | None = None) -> TraceRecord | None:
        with open_traces_db(self._sqlite_path) as conn:
            row = conn.execute(
                "SELECT trace_id, client_id, session_id, created_at, privacy_mode, payload_json "
                "FROM trace_records WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()
        if row is None:
            return None
        stored_client_id = row[1]
        if client_id is not None and stored_client_id != client_id:
            return None
        payload = json.loads(row[5])
        created_at = datetime.fromisoformat(row[3])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return TraceRecord(
            trace_id=row[0],
            client_id=stored_client_id,
            session_id=row[2],
            created_at=created_at,
            privacy_mode=row[4],
            payload=payload,
        )

    def delete_older_than(
        self, cutoff: datetime, *, client_id: str | None = None
    ) -> int:
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        cutoff_iso = cutoff.isoformat()
        with open_traces_db(self._sqlite_path) as conn:
            if client_id is None:
                cursor = conn.execute(
                    "DELETE FROM trace_records WHERE created_at < ?",
                    (cutoff_iso,),
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM trace_records WHERE client_id = ? AND created_at < ?",
                    (client_id, cutoff_iso),
                )
            conn.commit()
            return int(cursor.rowcount)
