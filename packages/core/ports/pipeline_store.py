from __future__ import annotations

from abc import ABC, abstractmethod

from packages.core.pipeline.models import PipelineRunRecord


class PipelineStore(ABC):
    @abstractmethod
    def create(self, record: PipelineRunRecord) -> PipelineRunRecord:
        raise NotImplementedError

    @abstractmethod
    def update(self, record: PipelineRunRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, client_id: str, pipeline_id: str) -> PipelineRunRecord | None:
        raise NotImplementedError

    @abstractmethod
    def list_runs(self, client_id: str, *, limit: int = 20) -> list[PipelineRunRecord]:
        raise NotImplementedError
