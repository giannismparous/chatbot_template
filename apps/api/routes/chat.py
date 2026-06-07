from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.chat_handlers import (
    _chat_request_from_dto,
    _v1_response,
    execute_chat,
    get_session_manager,
    handle_invalid_session,
    streaming_enabled,
    streaming_response_v1,
)
from apps.api.dependencies.config_http import ensure_tenant_config
from apps.api.dependencies.tenant import require_chat_tenant
from apps.api.schemas import ChatRequestDTO, ChatResponseDTO
from packages.core.tenant.context import TenantContext

router = APIRouter(prefix="/v1/chat", tags=["chat"])


@router.post("/respond")
def respond(
    payload: ChatRequestDTO,
    tenant: TenantContext = Depends(require_chat_tenant),
):
    ensure_tenant_config(tenant.client_id)
    if payload.stream and not streaming_enabled(tenant.client_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Streaming disabled for client.")

    try:
        prepared = get_session_manager().prepare_v1(_chat_request_from_dto(tenant, payload))
    except ValueError as exc:
        raise handle_invalid_session(exc) from exc

    response = execute_chat(prepared=prepared, original_message=payload.message)

    if payload.stream:
        return streaming_response_v1(response, debug=payload.debug)
    return _v1_response(response, debug=payload.debug)
