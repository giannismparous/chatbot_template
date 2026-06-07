from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class ConfigStore(ABC):
    @abstractmethod
    def get_clients_root(self) -> Path:
        raise NotImplementedError

    @abstractmethod
    def get_registry_path(self) -> Path:
        raise NotImplementedError

    @abstractmethod
    def load_registry(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_client_config_dir(self, client_id: str) -> Path:
        raise NotImplementedError
