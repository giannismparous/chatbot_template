from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AdminRole(str, Enum):
    PLATFORM_ADMIN = "platform_admin"
    CLIENT_ADMIN = "client_admin"


@dataclass(frozen=True)
class AdminContext:
    role: AdminRole
    client_id: str | None = None
    subject: str = "admin"
