from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class RetrievedChunk:
    id: str
    text: str
    source: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PublicSource:
    index: int
    title: str
    url: str
    score: float


@dataclass
class Escalation:
    type: str
    message: str
    contact_hint: Optional[str] = None


@dataclass
class ChatRequest:
    client_id: str
    message: str
    history: List[ChatMessage] = field(default_factory=list)
    mode: Optional[str] = None
    top_k: int = 5
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    effective_message: Optional[str] = None
    rewrite_reason: Optional[str] = None
    is_follow_up: bool = False


@dataclass
class ChatResponse:
    answer: str
    sources: List[PublicSource]
    confidence: float
    requires_human: bool = False
    escalation: Optional[Escalation] = None
    trace_id: str = ""
    trace: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
