from __future__ import annotations

from typing import Protocol

from packages.core.sessions.models import SessionHeader, SessionTurn


class SessionStore(Protocol):
    def get_session(self, client_id: str, session_id: str) -> SessionHeader | None: ...

    def create_session(
        self,
        *,
        client_id: str,
        session_id: str,
        user_id_hash: str | None,
        privacy_mode: str,
        ttl_hours: int,
    ) -> SessionHeader: ...

    def touch_session(self, client_id: str, session_id: str, *, ttl_hours: int) -> None: ...

    def load_turns(self, client_id: str, session_id: str, *, limit: int) -> list[SessionTurn]: ...

    def append_turn(self, client_id: str, session_id: str, turn: SessionTurn, *, max_turns: int) -> None: ...

    def delete_expired(self, client_id: str | None = None) -> int: ...
