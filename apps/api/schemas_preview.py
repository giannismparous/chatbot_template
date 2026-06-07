from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from apps.api.schemas import ChatMessageDTO, EscalationDTO
from apps.api.schemas_v2 import ConfidenceDTO, PublicSourceV2DTO


class PreviewRequestDTO(BaseModel):
    message: str
    session_id: Optional[str] = None
    history: List[ChatMessageDTO] = Field(default_factory=list)
    language: Optional[str] = None
    mode: Optional[str] = None
    top_k: int = 6
    stream: bool = False
    index_scope: str = "active"
    debug: bool = False


class PreviewSummaryDTO(BaseModel):
    rewrite_reason: Optional[str] = None
    is_follow_up: bool = False
    retrieved_count: int = 0
    no_context: bool = False
    regulated_mode: bool = False


class PreviewResponseDTO(BaseModel):
    answer: str
    sources: List[PublicSourceV2DTO] = Field(default_factory=list)
    confidence: ConfidenceDTO
    requires_human: bool = False
    escalation: Optional[EscalationDTO] = None
    trace_id: str = ""
    session_id: Optional[str] = None
    summary: PreviewSummaryDTO = Field(default_factory=PreviewSummaryDTO)
