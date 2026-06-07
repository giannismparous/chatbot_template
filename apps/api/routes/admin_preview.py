from __future__ import annotations

from contextlib import nullcontext

from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.chat_handlers import (
    _v2_response,
    execute_chat,
    get_session_manager,
    handle_invalid_session,
    streaming_enabled,
    streaming_response_v2,
)
from apps.api.dependencies.auth import require_admin_token
from apps.api.dependencies.config_http import ensure_tenant_config
from apps.api.dependencies.stack import get_stack
from apps.api.schemas_preview import PreviewRequestDTO, PreviewResponseDTO, PreviewSummaryDTO
from apps.api.schemas_v2 import ConfidenceDTO, PublicSourceV2DTO
from packages.core.admin.preview_filter import filter_preview_summary
from packages.core.admin.roles import AdminContext
from packages.core.chat.confidence_public import confidence_from_score
from packages.core.config.loader import TenantConfigLoader
from packages.core.domain.models import ChatMessage, ChatRequest
from packages.core.eval.index_scope import eval_index_scope
from packages.core.safety.config import apply_regulated_overrides
from packages.core.stack.factory import project_root
from packages.core.tenant.paths import safe_client_id

router = APIRouter(
    prefix="/v1/admin/clients",
    tags=["admin-preview"],
    dependencies=[Depends(require_admin_token)],
)


def _preview_summary(res, *, rewrite_reason: str | None, is_follow_up: bool, regulated_mode: bool) -> PreviewSummaryDTO:
    trace = res.trace or {}
    return PreviewSummaryDTO(
        rewrite_reason=rewrite_reason,
        is_follow_up=is_follow_up,
        retrieved_count=int(trace.get("retrieved_count") or 0),
        no_context=bool(trace.get("no_context")),
        regulated_mode=regulated_mode,
    )


@router.post("/{client_id}/preview")
def preview_chat(
    client_id: str,
    payload: PreviewRequestDTO,
    admin: AdminContext = Depends(require_admin_token),
):
    _ = admin
    cid = safe_client_id(client_id)
    ensure_tenant_config(cid)
    if payload.stream and not streaming_enabled(cid):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Streaming disabled for client.")

    scope = (payload.index_scope or "active").strip().lower()
    if scope not in {"active", "pending"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid index_scope.")

    stack = get_stack()
    clients_root = stack.config_store.get_clients_root()
    loader = TenantConfigLoader(
        clients_root=clients_root,
        domain_packs_root=project_root() / "packages" / "domain_packs",
    )
    merged = loader.load(cid)
    regulated_mode = bool(apply_regulated_overrides(merged).regulated_mode)

    request = ChatRequest(
        client_id=cid,
        message=payload.message,
        history=[ChatMessage(role=m.role, content=m.content) for m in payload.history],
        mode=payload.mode,
        top_k=payload.top_k,
        session_id=payload.session_id,
    )

    try:
        prepared = get_session_manager().prepare_v1(request)
    except ValueError as exc:
        raise handle_invalid_session(exc) from exc

    scope_ctx = (
        eval_index_scope(clients_root, cid, scope=scope)
        if scope == "pending"
        else nullcontext()
    )

    from apps.api.dependencies import container

    with scope_ctx:
        try:
            response = execute_chat(
                prepared=prepared,
                orchestrator=container.ORCHESTRATOR,
                original_message=payload.message,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    v2 = _v2_response(response, debug=payload.debug)
    summary = _preview_summary(
        response,
        rewrite_reason=prepared.rewrite.rewrite_reason if prepared.rewrite.is_follow_up else None,
        is_follow_up=prepared.rewrite.is_follow_up,
        regulated_mode=regulated_mode,
    )
    summary_payload = filter_preview_summary(admin, summary.model_dump())

    if payload.stream:
        return streaming_response_v2(response, debug=payload.debug)

    return PreviewResponseDTO(
        answer=v2.answer,
        sources=v2.sources,
        confidence=v2.confidence,
        requires_human=v2.requires_human,
        escalation=v2.escalation,
        trace_id=v2.trace_id,
        session_id=v2.session_id,
        summary=PreviewSummaryDTO(**summary_payload),
    )
