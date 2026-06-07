from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.chat_handlers import (
    _chat_request_from_v2,
    _v2_response,
    execute_chat,
    get_session_manager,
    handle_invalid_session,
    streaming_enabled,
    streaming_response_v2,
)
from apps.api.dependencies.config_http import ensure_tenant_config
from apps.api.dependencies.tenant import require_chat_tenant
from apps.api.schemas_v2 import ChatRequestV2DTO, ChatResponseV2DTO
from packages.core.tenant.context import TenantContext

router = APIRouter(prefix="/v2/chat", tags=["chat-v2"])


@router.post("/respond")
def respond_v2(
    payload: ChatRequestV2DTO,
    tenant: TenantContext = Depends(require_chat_tenant),
):
    ensure_tenant_config(tenant.client_id)
    if payload.stream and not streaming_enabled(tenant.client_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Streaming disabled for client.")

    try:
        prepared = get_session_manager().prepare_v2(_chat_request_from_v2(tenant, payload))
    except ValueError as exc:
        raise handle_invalid_session(exc) from exc

    response = execute_chat(prepared=prepared, original_message=payload.message)

    if payload.stream:
        return streaming_response_v2(response, debug=payload.debug)
    return _v2_response(response, debug=payload.debug)
