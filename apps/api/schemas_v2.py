from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from apps.api.schemas import ChatMessageDTO, EscalationDTO


class ConfidenceDTO(BaseModel):
    level: str
    reason: str


class PublicSourceV2DTO(BaseModel):
    index: int
    title: str
    url: str
    clickable: bool = True


class ChatRequestV2DTO(BaseModel):
    client_id: Optional[str] = None
    message: str
    history: List[ChatMessageDTO] = Field(default_factory=list)
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    language: Optional[str] = None
    mode: Optional[str] = None
    top_k: int = 6
    stream: bool = False
    debug: bool = False


class ChatResponseV2DTO(BaseModel):
    answer: str
    sources: List[PublicSourceV2DTO] = Field(default_factory=list)
    confidence: ConfidenceDTO
    requires_human: bool = False
    escalation: Optional[EscalationDTO] = None
    trace_id: str = ""
    session_id: Optional[str] = None
