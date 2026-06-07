from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from packages.adapters.traces.sqlite_db import open_traces_db
from packages.core.ports.session_store import SessionStore
from packages.core.sessions.models import SessionHeader, SessionTurn, utc_now


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class LocalSqliteSessionStore(SessionStore):
    def __init__(self, sqlite_path: str | Path) -> None:
        self._sqlite_path = Path(sqlite_path)

    def get_session(self, client_id: str, session_id: str) -> SessionHeader | None:
        with open_traces_db(self._sqlite_path) as conn:
            row = conn.execute(
                """
                SELECT user_id_hash, privacy_mode, turn_count, created_at, updated_at, expires_at
                FROM chat_sessions WHERE client_id = ? AND session_id = ?
                """,
                (client_id, session_id),
            ).fetchone()
        if row is None:
            return None
        expires_at = _parse_dt(row[5])
        if expires_at <= utc_now():
            return None
        return SessionHeader(
            client_id=client_id,
            session_id=session_id,
            user_id_hash=row[0],
            privacy_mode=row[1],
            turn_count=int(row[2]),
            created_at=_parse_dt(row[3]),
            updated_at=_parse_dt(row[4]),
            expires_at=expires_at,
        )

    def create_session(
        self,
        *,
        client_id: str,
        session_id: str,
        user_id_hash: str | None,
        privacy_mode: str,
        ttl_hours: int,
    ) -> SessionHeader:
        now = utc_now()
        expires = now + timedelta(hours=ttl_hours)
        with open_traces_db(self._sqlite_path) as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    client_id, session_id, user_id_hash, privacy_mode, turn_count,
                    created_at, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    client_id,
                    session_id,
                    user_id_hash,
                    privacy_mode,
                    now.isoformat(),
                    now.isoformat(),
                    expires.isoformat(),
                ),
            )
            conn.commit()
        return SessionHeader(
            client_id=client_id,
            session_id=session_id,
            user_id_hash=user_id_hash,
            privacy_mode=privacy_mode,
            turn_count=0,
            created_at=now,
            updated_at=now,
            expires_at=expires,
        )

    def touch_session(self, client_id: str, session_id: str, *, ttl_hours: int) -> None:
        now = utc_now()
        expires = now + timedelta(hours=ttl_hours)
        with open_traces_db(self._sqlite_path) as conn:
            conn.execute(
                """
                UPDATE chat_sessions SET updated_at = ?, expires_at = ?
                WHERE client_id = ? AND session_id = ?
                """,
                (now.isoformat(), expires.isoformat(), client_id, session_id),
            )
            conn.commit()

    def load_turns(self, client_id: str, session_id: str, *, limit: int) -> list[SessionTurn]:
        with open_traces_db(self._sqlite_path) as conn:
            rows = conn.execute(
                """
                SELECT turn_index, role, content, trace_id, rewrite_reason, is_follow_up,
                       created_at, flags_json
                FROM chat_session_turns
                WHERE client_id = ? AND session_id = ?
                ORDER BY turn_index DESC, role DESC
                LIMIT ?
                """,
                (client_id, session_id, limit),
            ).fetchall()
        turns: list[SessionTurn] = []
        for row in reversed(rows):
            turns.append(
                SessionTurn(
                    turn_index=int(row[0]),
                    role=str(row[1]),
                    content=row[2],
                    trace_id=row[3],
                    rewrite_reason=row[4],
                    is_follow_up=bool(row[5]),
                    created_at=_parse_dt(row[6]),
                    flags=json.loads(row[7] or "{}"),
                )
            )
        return turns

    def append_turn(self, client_id: str, session_id: str, turn: SessionTurn, *, max_turns: int) -> None:
        now = utc_now()
        with open_traces_db(self._sqlite_path) as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(turn_index), -1) FROM chat_session_turns WHERE client_id = ? AND session_id = ?",
                (client_id, session_id),
            ).fetchone()
            next_index = int(row[0]) + 1 if row else 0
            conn.execute(
                """
                INSERT INTO chat_session_turns (
                    client_id, session_id, turn_index, role, content, trace_id,
                    rewrite_reason, is_follow_up, created_at, flags_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client_id,
                    session_id,
                    next_index,
                    turn.role,
                    turn.content,
                    turn.trace_id,
                    turn.rewrite_reason,
                    1 if turn.is_follow_up else 0,
                    (turn.created_at or now).isoformat(),
                    json.dumps(turn.flags or {}),
                ),
            )
            conn.execute(
                """
                UPDATE chat_sessions SET turn_count = turn_count + 1, updated_at = ?
                WHERE client_id = ? AND session_id = ?
                """,
                (now.isoformat(), client_id, session_id),
            )
            max_rows = max(2, max_turns * 2)
            count_row = conn.execute(
                "SELECT COUNT(*) FROM chat_session_turns WHERE client_id = ? AND session_id = ?",
                (client_id, session_id),
            ).fetchone()
            total = int(count_row[0]) if count_row else 0
            if total > max_rows:
                excess = total - max_rows
                conn.execute(
                    """
                    DELETE FROM chat_session_turns WHERE id IN (
                        SELECT id FROM chat_session_turns
                        WHERE client_id = ? AND session_id = ?
                        ORDER BY turn_index ASC, id ASC
                        LIMIT ?
                    )
                    """,
                    (client_id, session_id, excess),
                )
            conn.commit()

    def delete_expired(self, client_id: str | None = None) -> int:
        now = utc_now().isoformat()
        with open_traces_db(self._sqlite_path) as conn:
            if client_id:
                rows = conn.execute(
                    "SELECT session_id FROM chat_sessions WHERE client_id = ? AND expires_at <= ?",
                    (client_id, now),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT client_id, session_id FROM chat_sessions WHERE expires_at <= ?",
                    (now,),
                ).fetchall()
            for row in rows:
                if client_id:
                    conn.execute(
                        "DELETE FROM chat_session_turns WHERE client_id = ? AND session_id = ?",
                        (client_id, row[0]),
                    )
                    conn.execute(
                        "DELETE FROM chat_sessions WHERE client_id = ? AND session_id = ?",
                        (client_id, row[0]),
                    )
                else:
                    conn.execute(
                        "DELETE FROM chat_session_turns WHERE client_id = ? AND session_id = ?",
                        (row[0], row[1]),
                    )
                    conn.execute(
                        "DELETE FROM chat_sessions WHERE client_id = ? AND session_id = ?",
                        (row[0], row[1]),
                    )
            conn.commit()
            return len(rows)
