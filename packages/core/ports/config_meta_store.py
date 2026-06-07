from __future__ import annotations

from abc import ABC, abstractmethod

from packages.core.control_plane.models import ConfigMetaRecord


class ConfigMetaStore(ABC):
    @abstractmethod
    def get_meta(self, client_id: str, config_key: str) -> ConfigMetaRecord | None:
        raise NotImplementedError

    @abstractmethod
    def put_meta(self, record: ConfigMetaRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_meta(self, client_id: str) -> list[ConfigMetaRecord]:
        raise NotImplementedError
