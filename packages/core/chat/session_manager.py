from __future__ import annotations

from dataclasses import dataclass, replace

from packages.core.config.loader import TenantConfigLoader
from packages.core.domain.models import ChatMessage, ChatRequest, ChatResponse
from packages.core.privacy.config import normalize_privacy
from packages.core.ports.session_store import SessionStore
from packages.core.sessions.follow_up_rewrite import RewriteResult, rewrite_follow_up_query
from packages.core.sessions.models import (
    SessionConfig,
    SessionTurn,
    generate_session_id,
    parse_session_config,
    validate_session_id,
)
from packages.core.sessions.privacy import (
    hash_session_user_id,
    redact_for_session_storage,
    session_content_allowed,
)


@dataclass
class PreparedChat:
    request: ChatRequest
    rewrite: RewriteResult
    session_config: SessionConfig
    auto_generated_session: bool = False


class ChatSessionManager:
    def __init__(self, *, session_store: SessionStore, config_loader: TenantConfigLoader) -> None:
        self._session_store = session_store
        self._config_loader = config_loader

    def prepare_v1(self, request: ChatRequest) -> PreparedChat:
        merged = self._config_loader.load(request.client_id)
        privacy = normalize_privacy(merged.privacy or {})
        session_cfg = parse_session_config(merged.privacy or {})
        history = list(request.history)
        session_id = request.session_id

        if session_id:
            session_id = validate_session_id(session_id)
            if session_cfg.enabled:
                history = self._merge_session_history(
                    request.client_id,
                    session_id,
                    history,
                    limit=min(12, session_cfg.max_turns),
                )

        rewrite = rewrite_follow_up_query(
            request.message,
            history,
            merged.locale or {},
            content_allowed=session_content_allowed(privacy),
        )
        effective = replace(request, session_id=session_id, history=history)
        return PreparedChat(
            request=self._with_effective_message(effective, rewrite),
            rewrite=rewrite,
            session_config=session_cfg,
        )

    def prepare_v2(self, request: ChatRequest) -> PreparedChat:
        merged = self._config_loader.load(request.client_id)
        privacy = normalize_privacy(merged.privacy or {})
        session_cfg = parse_session_config(merged.privacy or {})
        history = list(request.history)
        auto_generated = False
        session_id = request.session_id

        if session_id:
            session_id = validate_session_id(session_id)
        elif session_cfg.enabled:
            session_id = generate_session_id()
            auto_generated = True

        if session_id and session_cfg.enabled:
            history = self._merge_session_history(
                request.client_id,
                session_id,
                history,
                limit=min(12, session_cfg.max_turns),
            )
            self._ensure_session_header(request, session_id, session_cfg, privacy.mode)

        rewrite = rewrite_follow_up_query(
            request.message,
            history,
            merged.locale or {},
            content_allowed=session_content_allowed(privacy) if session_id else False,
        )
        effective = replace(request, session_id=session_id, history=history)
        return PreparedChat(
            request=self._with_effective_message(effective, rewrite),
            rewrite=rewrite,
            session_config=session_cfg,
            auto_generated_session=auto_generated,
        )

    def persist_turns(
        self,
        prepared: PreparedChat,
        response: ChatResponse,
        *,
        original_message: str,
    ) -> None:
        session_id = prepared.request.session_id
        if not session_id or not prepared.session_config.enabled:
            return
        merged = self._config_loader.load(prepared.request.client_id)
        privacy = normalize_privacy(merged.privacy or {})
        session_cfg = prepared.session_config
        self._ensure_session_header(prepared.request, session_id, session_cfg, privacy.mode)
        user_content = redact_for_session_storage(original_message, privacy)
        assistant_content = redact_for_session_storage(response.answer, privacy)
        self._session_store.append_turn(
            prepared.request.client_id,
            session_id,
            SessionTurn(
                role="user",
                content=user_content,
                trace_id=response.trace_id,
                rewrite_reason=prepared.rewrite.rewrite_reason if prepared.rewrite.is_follow_up else None,
                is_follow_up=prepared.rewrite.is_follow_up,
            ),
            max_turns=session_cfg.max_turns,
        )
        self._session_store.append_turn(
            prepared.request.client_id,
            session_id,
            SessionTurn(role="assistant", content=assistant_content, trace_id=response.trace_id),
            max_turns=session_cfg.max_turns,
        )
        self._session_store.touch_session(
            prepared.request.client_id,
            session_id,
            ttl_hours=session_cfg.ttl_hours,
        )

    def _ensure_session_header(
        self,
        request: ChatRequest,
        session_id: str,
        session_cfg: SessionConfig,
        privacy_mode: str,
    ) -> None:
        existing = self._session_store.get_session(request.client_id, session_id)
        if existing:
            return
        merged = self._config_loader.load(request.client_id)
        privacy = normalize_privacy(merged.privacy or {})
        user_hash = hash_session_user_id(request.user_id, client_id=request.client_id, privacy=privacy)
        self._session_store.create_session(
            client_id=request.client_id,
            session_id=session_id,
            user_id_hash=user_hash,
            privacy_mode=privacy_mode,
            ttl_hours=session_cfg.ttl_hours,
        )

    def _merge_session_history(
        self,
        client_id: str,
        session_id: str,
        client_history: list[ChatMessage],
        *,
        limit: int,
    ) -> list[ChatMessage]:
        if self._session_store.get_session(client_id, session_id) is None:
            return client_history
        turns = self._session_store.load_turns(client_id, session_id, limit=limit)
        server_history = [
            ChatMessage(role=t.role, content=t.content or "")
            for t in turns
            if t.content
        ]
        if not server_history:
            return client_history
        if not client_history:
            return server_history
        return server_history + client_history

    @staticmethod
    def _with_effective_message(request: ChatRequest, rewrite: RewriteResult) -> ChatRequest:
        return replace(
            request,
            effective_message=rewrite.rewritten_query,
            rewrite_reason=rewrite.rewrite_reason,
            is_follow_up=rewrite.is_follow_up,
        )
