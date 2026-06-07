from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Sequence

from .models import RetrievedChunk


class LLMProvider(ABC):
    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        messages: Sequence[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
    ) -> str:
        raise NotImplementedError


class KnowledgeConnector(ABC):
    @abstractmethod
    def search(self, query: str, limit: int = 10, **kwargs: Any) -> List[RetrievedChunk]:
        raise NotImplementedError


class Retriever(ABC):
    @abstractmethod
    def retrieve(
        self,
        query: str,
        limit: int = 5,
        mode: str = "hybrid_local",
        **kwargs: Any,
    ) -> List[RetrievedChunk]:
        raise NotImplementedError


class PromptPolicy(ABC):
    @abstractmethod
    def build_system_prompt(self, client_id: str, mode: str) -> str:
        raise NotImplementedError


class ThemeProvider(ABC):
    @abstractmethod
    def get_theme(self, client_id: str) -> Dict[str, Any]:
        raise NotImplementedError


class VectorStore(ABC):
    @abstractmethod
    def upsert(self, items: Iterable[Dict[str, Any]]) -> None:
        raise NotImplementedError

    @abstractmethod
    def query(self, vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        raise NotImplementedError
