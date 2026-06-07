from __future__ import annotations

from abc import ABC, abstractmethod


class AuthProvider(ABC):
    @abstractmethod
    def resolve_widget_key(self, public_key: str, origin: str | None) -> str:
        """Map x-client-key (+ optional Origin) to client_id or raise TenantAuthError."""
        raise NotImplementedError
