from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatMessageDTO(BaseModel):
    role: str
    content: str


class ChatRequestDTO(BaseModel):
    client_id: Optional[str] = None
    message: str
    history: List[ChatMessageDTO] = Field(default_factory=list)
    mode: Optional[str] = None
    top_k: int = 5
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    language: Optional[str] = None
    stream: bool = False
    debug: bool = False


class SourceDTO(BaseModel):
    index: int
    title: str
    url: str
    score: float


class EscalationDTO(BaseModel):
    type: str
    message: str
    contact_hint: Optional[str] = None


class ChatResponseDTO(BaseModel):
    answer: str
    sources: List[SourceDTO]
    confidence: float
    requires_human: bool = False
    escalation: Optional[EscalationDTO] = None
    trace_id: str = ""
    trace: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None


class TraceDetailDTO(BaseModel):
    trace_id: str
    client_id: str
    session_id: Optional[str] = None
    created_at: str
    privacy_mode: str
    trace: Dict[str, Any] = Field(default_factory=dict)
