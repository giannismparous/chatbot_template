from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

_SESSION_ID_PATTERN = re.compile(r"^sess_[a-zA-Z0-9_-]{8,64}$")


@dataclass
class SessionConfig:
    enabled: bool = True
    max_turns: int = 20
    ttl_hours: int = 24


@dataclass
class SessionHeader:
    client_id: str
    session_id: str
    user_id_hash: str | None
    privacy_mode: str
    turn_count: int
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


@dataclass
class SessionTurn:
    role: str
    content: str | None = None
    trace_id: str | None = None
    rewrite_reason: str | None = None
    is_follow_up: bool = False
    turn_index: int = 0
    created_at: datetime | None = None
    flags: dict[str, Any] = field(default_factory=dict)


def parse_session_config(privacy: dict[str, Any]) -> SessionConfig:
    raw = privacy.get("session") or {}
    if not isinstance(raw, dict):
        raw = {}
    return SessionConfig(
        enabled=bool(raw.get("enabled", True)),
        max_turns=max(2, int(raw.get("max_turns", 20))),
        ttl_hours=max(1, int(raw.get("ttl_hours", 24))),
    )


def validate_session_id(session_id: str) -> str:
    value = (session_id or "").strip()
    if not value or not _SESSION_ID_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid session_id: {session_id!r}")
    if ".." in value or "/" in value or "\\" in value:
        raise ValueError(f"Invalid session_id: {session_id!r}")
    return value


def generate_session_id() -> str:
    import uuid

    return f"sess_{uuid.uuid4().hex[:16]}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
