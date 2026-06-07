from __future__ import annotations

from typing import Iterator

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse

from apps.api.dependencies import container
from apps.api.dependencies.config_http import ensure_tenant_config
from apps.api.dependencies.stack import get_stack
from apps.api.schemas import ChatRequestDTO, ChatResponseDTO, EscalationDTO, SourceDTO
from apps.api.schemas_v2 import (
    ChatRequestV2DTO,
    ChatResponseV2DTO,
    ConfidenceDTO,
    PublicSourceV2DTO,
)
from packages.core.chat.confidence_public import confidence_from_score
from packages.core.chat.session_manager import ChatSessionManager, PreparedChat
from packages.core.chat.streaming import assert_safe_done_payload, stream_buffered_answer
from packages.core.config.loader import TenantConfigLoader
from packages.core.domain.models import ChatMessage, ChatRequest, ChatResponse
from packages.core.orchestrator.chat_orchestrator import ChatOrchestrator
from packages.core.tenant.context import TenantContext


def get_session_manager() -> ChatSessionManager:
    stack = get_stack()
    loader = TenantConfigLoader(
        clients_root=stack.config_store.get_clients_root(),
        domain_packs_root=container.ROOT / "packages" / "domain_packs",
    )
    return ChatSessionManager(session_store=stack.session_store, config_loader=loader)


def _chat_request_from_dto(tenant: TenantContext, payload: ChatRequestDTO) -> ChatRequest:
    return ChatRequest(
        client_id=tenant.client_id,
        message=payload.message,
        history=[ChatMessage(role=m.role, content=m.content) for m in payload.history],
        mode=payload.mode,
        top_k=payload.top_k,
        user_id=payload.user_id,
        session_id=payload.session_id,
    )


def _chat_request_from_v2(tenant: TenantContext, payload: ChatRequestV2DTO) -> ChatRequest:
    return ChatRequest(
        client_id=tenant.client_id,
        message=payload.message,
        history=[ChatMessage(role=m.role, content=m.content) for m in payload.history],
        mode=payload.mode,
        top_k=payload.top_k,
        user_id=payload.user_id,
        session_id=payload.session_id,
    )


def _v1_response(res: ChatResponse, *, debug: bool) -> ChatResponseDTO:
    escalation = None
    if res.escalation is not None:
        escalation = EscalationDTO(
            type=res.escalation.type,
            message=res.escalation.message,
            contact_hint=res.escalation.contact_hint,
        )
    trace = res.trace if debug else {}
    return ChatResponseDTO(
        answer=res.answer,
        confidence=res.confidence,
        requires_human=res.requires_human,
        escalation=escalation,
        trace_id=res.trace_id,
        trace=trace,
        session_id=res.session_id,
        sources=[
            SourceDTO(index=s.index, title=s.title, url=s.url, score=s.score)
            for s in res.sources
        ],
    )


def _v2_response(res: ChatResponse, *, debug: bool) -> ChatResponseV2DTO:
    escalation = None
    if res.escalation is not None:
        escalation = EscalationDTO(
            type=res.escalation.type,
            message=res.escalation.message,
            contact_hint=res.escalation.contact_hint,
        )
    no_context = res.confidence <= 0.0 and not res.sources
    public_conf = confidence_from_score(res.confidence, no_context=no_context)
    return ChatResponseV2DTO(
        answer=res.answer,
        sources=[
            PublicSourceV2DTO(index=s.index, title=s.title, url=s.url, clickable=True)
            for s in res.sources
        ],
        confidence=ConfidenceDTO(level=public_conf.level, reason=public_conf.reason),
        requires_human=res.requires_human,
        escalation=escalation,
        trace_id=res.trace_id if debug else res.trace_id,
        session_id=res.session_id,
    )


def _v2_done_payload(dto: ChatResponseV2DTO) -> dict:
    return dto.model_dump(exclude_none=True)


def _should_emit_chunks(res: ChatResponse) -> bool:
    if res.confidence <= 0.0 and not res.sources:
        return False
    if res.requires_human and not res.sources:
        return False
    return bool(res.answer)


def execute_chat(
    *,
    prepared: PreparedChat,
    orchestrator: ChatOrchestrator | None = None,
    original_message: str,
) -> ChatResponse:
    orch = orchestrator or container.ORCHESTRATOR
    response = orch.answer(prepared.request)
    if prepared.request.session_id:
        response = ChatResponse(
            answer=response.answer,
            sources=response.sources,
            confidence=response.confidence,
            requires_human=response.requires_human,
            escalation=response.escalation,
            trace_id=response.trace_id,
            trace=response.trace,
            session_id=prepared.request.session_id,
        )
    get_session_manager().persist_turns(prepared, response, original_message=original_message)
    return response


def handle_invalid_session(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def streaming_response_v1(res: ChatResponse, *, debug: bool) -> StreamingResponse:
    dto = _v1_response(res, debug=debug)
    done = {
        "answer": dto.answer,
        "sources": [s.model_dump() for s in dto.sources],
        "confidence": dto.confidence,
        "requires_human": dto.requires_human,
        "escalation": dto.escalation.model_dump() if dto.escalation else None,
        "trace_id": dto.trace_id,
        "session_id": dto.session_id,
    }
    assert_safe_done_payload(done)

    def _gen() -> Iterator[str]:
        yield from stream_buffered_answer(
            answer=res.answer,
            done_payload=done,
            emit_chunks=_should_emit_chunks(res),
        )

    return StreamingResponse(_gen(), media_type="text/event-stream")


def streaming_response_v2(res: ChatResponse, *, debug: bool) -> StreamingResponse:
    dto = _v2_response(res, debug=debug)
    done = _v2_done_payload(dto)
    assert_safe_done_payload(done)

    def _gen() -> Iterator[str]:
        yield from stream_buffered_answer(
            answer=res.answer,
            done_payload=done,
            emit_chunks=_should_emit_chunks(res),
        )

    return StreamingResponse(_gen(), media_type="text/event-stream")


def streaming_enabled(client_id: str) -> bool:
    merged = container.TENANT_CONFIG.load(client_id)
    features = (merged.themes or {}).get("features") or {}
    return bool(features.get("streaming_enabled", True))
