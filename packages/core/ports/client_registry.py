from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from packages.core.control_plane.models import CreateClientResult, RotateWidgetKeyResult, WidgetKeyRecord


class ClientRegistryStore(ABC):
    @abstractmethod
    def list_clients(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_client(self, client_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def client_exists(self, client_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def create_client_record(
        self,
        *,
        client_id: str,
        display_name: str,
        domain_pack: str,
        allowed_origins: list[str] | None,
        reveal_widget_key: bool,
    ) -> CreateClientResult:
        raise NotImplementedError

    @abstractmethod
    def list_widget_keys(self, client_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def rotate_widget_key(
        self,
        client_id: str,
        *,
        allowed_origins: list[str] | None = None,
        revoke_key_id: str | None = None,
    ) -> RotateWidgetKeyResult:
        raise NotImplementedError

    @abstractmethod
    def revoke_widget_key(self, client_id: str, key_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def find_active_keys_by_prefix(self, prefix: str) -> list[WidgetKeyRecord]:
        raise NotImplementedError

    @abstractmethod
    def increment_config_revision(self, client_id: str) -> int:
        raise NotImplementedError

    @abstractmethod
    def get_config_revision(self, client_id: str) -> int:
        raise NotImplementedError
