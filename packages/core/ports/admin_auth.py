from __future__ import annotations

from abc import ABC, abstractmethod

from packages.core.admin.roles import AdminContext


class AdminAuthError(Exception):
    pass


class AdminAuthProvider(ABC):
    @abstractmethod
    def resolve_admin(self, credential: str | None) -> AdminContext:
        raise NotImplementedError
