from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed_texts(self, texts: Sequence[str], *, model: str) -> list[list[float]]:
        raise NotImplementedError

    @property
    def expected_dims(self) -> int | None:
        return None
