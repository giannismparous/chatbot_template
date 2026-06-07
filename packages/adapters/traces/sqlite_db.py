from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def traces_db_path() -> Path:
    import os

    from packages.core.stack.factory import project_root

    raw = os.getenv("TRACES_SQLITE_PATH", "").strip()
    if raw:
        return Path(raw)
    return project_root() / "data" / "traces.sqlite3"


def ensure_traces_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS trace_records (
            trace_id     TEXT PRIMARY KEY,
            client_id    TEXT NOT NULL,
            session_id   TEXT,
            created_at   TEXT NOT NULL,
            privacy_mode TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_trace_client_created
            ON trace_records (client_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS chat_sessions (
            client_id       TEXT NOT NULL,
            session_id      TEXT NOT NULL,
            user_id_hash    TEXT,
            privacy_mode    TEXT NOT NULL,
            turn_count      INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            expires_at      TEXT NOT NULL,
            PRIMARY KEY (client_id, session_id)
        );

        CREATE TABLE IF NOT EXISTS chat_session_turns (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id       TEXT NOT NULL,
            session_id      TEXT NOT NULL,
            turn_index      INTEGER NOT NULL,
            role            TEXT NOT NULL,
            content         TEXT,
            trace_id        TEXT,
            rewrite_reason  TEXT,
            is_follow_up    INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT NOT NULL,
            flags_json      TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_session_turns_lookup
            ON chat_session_turns (client_id, session_id, turn_index);

        CREATE TABLE IF NOT EXISTS client_metrics (
            client_id          TEXT PRIMARY KEY,
            updated_at         TEXT NOT NULL,
            total_chats        INTEGER NOT NULL DEFAULT 0,
            no_context         INTEGER NOT NULL DEFAULT 0,
            crisis             INTEGER NOT NULL DEFAULT 0,
            input_blocked      INTEGER NOT NULL DEFAULT 0,
            provider_fallback  INTEGER NOT NULL DEFAULT 0,
            latency_ms_sum     INTEGER NOT NULL DEFAULT 0,
            latency_ms_count   INTEGER NOT NULL DEFAULT 0,
            confidence_buckets TEXT NOT NULL DEFAULT '{}'
        );
        """
    )


def open_traces_db(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or traces_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    ensure_traces_schema(conn)
    return conn


def empty_confidence_buckets() -> dict[str, int]:
    from packages.core.ports.metrics_store import CONFIDENCE_BUCKETS

    return {label: 0 for label in CONFIDENCE_BUCKETS}


def parse_confidence_buckets(raw: str | None) -> dict[str, int]:
    buckets = empty_confidence_buckets()
    if not raw:
        return buckets
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return buckets
    if not isinstance(loaded, dict):
        return buckets
    for key in buckets:
        value = loaded.get(key, 0)
        if isinstance(value, int) and value >= 0:
            buckets[key] = value
    return buckets
