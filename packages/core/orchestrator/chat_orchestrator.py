from __future__ import annotations

from time import perf_counter
from typing import Dict, List

from packages.core.citations.context_builder import build_citation_context, format_numbered_context
from packages.core.citations.enforcer import enforce_citations
from packages.core.chat.confidence_public import compute_retrieval_confidence
from packages.core.config.loader import TenantConfigLoader
from packages.core.domain.interfaces import LLMProvider
from packages.core.domain.models import ChatRequest, ChatResponse, Escalation
from packages.core.chat.answer_completeness import finalize_answer_text
from packages.core.llm.models import LLMOutcome
from packages.core.privacy.config import PrivacyContext, TraceDraft, normalize_privacy
from packages.core.privacy.logging import privacy_safe_log
from packages.core.privacy.processor import gate_trace
from packages.core.ports.metrics_store import MetricsStore
from packages.core.ports.trace_store import TraceStore
from packages.core.safety.config import apply_regulated_overrides
from packages.core.safety.crisis_filter import check_crisis
from packages.core.safety.disclaimer_injector import inject_disclaimers
from packages.core.safety.escalation import build_dont_know_escalation, check_human_handoff
from packages.core.safety.input_guard import check_input_guard
from packages.core.safety.regulated_citation import enforce_regulated_citations
from packages.core.safety.unsafe_output_sanitizer import sanitize_output
from packages.core.traces.models import TraceRecord
from packages.core.traces.noop_stores import NOOP_METRICS_STORE, NOOP_TRACE_STORE
from packages.core.traces.persistence import should_persist_trace


class ChatOrchestrator:
    def __init__(
        self,
        llm_provider: LLMProvider,
        retriever,
        prompt_policy,
        config_loader: TenantConfigLoader,
        *,
        default_model: str = "",
        stack_profile: str = "local",
        trace_store: TraceStore | None = None,
        metrics_store: MetricsStore | None = None,
    ) -> None:
        self._llm_provider = llm_provider
        self._retriever = retriever
        self._prompt_policy = prompt_policy
        self._config_loader = config_loader
        self._default_model = default_model
        self._stack_profile = stack_profile
        self._trace_store = trace_store or NOOP_TRACE_STORE
        self._metrics_store = metrics_store or NOOP_METRICS_STORE

    def _retrieval_query(self, request: ChatRequest) -> str:
        return (request.effective_message or request.message).strip()

    def answer(self, request: ChatRequest) -> ChatResponse:
        started_at = perf_counter()
        merged = self._config_loader.load(request.client_id)
        effective = apply_regulated_overrides(merged)
        mode = request.mode or "hybrid_local"
        privacy_cfg = merged.privacy or {}
        retrieval_query = self._retrieval_query(request)

        crisis = check_crisis(request.message, effective)
        if crisis is not None:
            return self._finalize_response(
                request=request,
                privacy_cfg=privacy_cfg,
                started_at=started_at,
                answer=crisis.answer,
                sources=[],
                confidence=0.0,
                requires_human=crisis.requires_human,
                escalation=crisis.escalation,
                draft=TraceDraft(
                    operational={
                        **crisis.trace,
                        "mode": mode,
                        "llm_skipped": True,
                        "retrieval_skipped": True,
                    },
                    input=self._input_section(request),
                ),
            )

        input_block = check_input_guard(request.message, effective)
        if input_block is not None:
            return self._finalize_response(
                request=request,
                privacy_cfg=privacy_cfg,
                started_at=started_at,
                answer=input_block.answer,
                sources=[],
                confidence=0.0,
                requires_human=input_block.requires_human,
                escalation=input_block.escalation,
                draft=TraceDraft(
                    operational={
                        **input_block.trace,
                        "mode": mode,
                        "llm_skipped": True,
                        "retrieval_skipped": True,
                    },
                    input=self._input_section(request),
                ),
            )

        handoff = check_human_handoff(request.message, effective.escalation_rules)
        if handoff is not None:
            return self._finalize_response(
                request=request,
                privacy_cfg=privacy_cfg,
                started_at=started_at,
                answer=handoff.message,
                sources=[],
                confidence=0.0,
                requires_human=True,
                escalation=handoff,
                draft=TraceDraft(
                    operational={
                        "mode": mode,
                        "human_handoff": True,
                        "llm_skipped": True,
                        "retrieval_skipped": True,
                    },
                    input=self._input_section(request),
                ),
            )

        retrieval_meta: dict = {}
        dense_skip_reason: str | None = None

        if hasattr(self._retriever, "retrieve_with_outcome"):
            outcome = self._retriever.retrieve_with_outcome(
                retrieval_query,
                limit=request.top_k,
                mode=mode,
                client_id=request.client_id,
            )
            docs = outcome.chunks
            no_context = outcome.no_context
            no_context_message = outcome.no_context_message
            retrieval_meta = outcome.meta or {}
            dense_skip_reason = outcome.dense_skip_reason
        else:
            docs = self._retriever.retrieve(
                retrieval_query,
                limit=request.top_k,
                mode=mode,
                client_id=request.client_id,
            )
            no_context = not docs
            no_context_message = None

        if no_context:
            escalation = build_dont_know_escalation(effective.escalation_rules)
            operational: dict = {
                "mode": mode,
                "retrieved_count": 0,
                "no_context": True,
                "llm_skipped": True,
            }
            if dense_skip_reason:
                operational["dense_skip_reason"] = dense_skip_reason
            return self._finalize_response(
                request=request,
                privacy_cfg=privacy_cfg,
                started_at=started_at,
                answer=no_context_message or escalation.message,
                sources=[],
                confidence=0.0,
                requires_human=False,
                escalation=escalation,
                draft=TraceDraft(
                    operational=operational,
                    input=self._input_section(request),
                    retrieval={"meta": retrieval_meta} if retrieval_meta else None,
                ),
            )

        citation_context = build_citation_context(docs)
        system_prompt = self._prompt_policy.build_system_prompt(request.client_id, mode)
        messages = self._build_messages(request.message, request.history, citation_context)
        llm_outcome = self._call_llm(system_prompt, messages, merged.llm or {})
        llm_trace = self._llm_trace_from_outcome(llm_outcome)

        if llm_outcome.fallback_used or llm_outcome.dev_placeholder:
            return self._finalize_fallback_response(
                request=request,
                privacy_cfg=privacy_cfg,
                started_at=started_at,
                llm_outcome=llm_outcome,
                effective=effective,
                mode=mode,
                docs=docs,
                dense_skip_reason=dense_skip_reason,
                llm_trace=llm_trace,
                llm_config=merged.llm or {},
            )

        llm_text, answer_trimmed = finalize_answer_text(
            llm_outcome.text,
            truncated=llm_outcome.truncated,
        )
        if answer_trimmed:
            llm_outcome = LLMOutcome(
                text=llm_text,
                model_used=llm_outcome.model_used,
                provider=llm_outcome.provider,
                blocked=llm_outcome.blocked,
                block_reason=llm_outcome.block_reason,
                fallback_used=llm_outcome.fallback_used,
                dev_placeholder=llm_outcome.dev_placeholder,
                truncated=llm_outcome.truncated,
                attempts=llm_outcome.attempts,
            )
            llm_trace = {**llm_trace, "answer_trimmed_incomplete": True}

        citation_result = enforce_citations(
            llm_outcome.text,
            citation_context,
            effective.source_whitelist,
        )
        answer = citation_result.answer
        claim_failures: list[str] = []

        if effective.regulated_mode:
            regulated_result = enforce_regulated_citations(
                answer,
                citation_context,
                effective.guardrails,
                compiled_factual_patterns=effective.compiled.regulated_factual_patterns,
                compiled_exempt_patterns=effective.compiled.regulated_exempt_patterns,
            )
            claim_failures = regulated_result.claim_failures
            if regulated_result.hard_refused:
                escalation = build_dont_know_escalation(effective.escalation_rules)
                return self._finalize_response(
                    request=request,
                    privacy_cfg=privacy_cfg,
                    started_at=started_at,
                    answer=escalation.message,
                    sources=[],
                    confidence=0.0,
                    requires_human=True,
                    escalation=escalation,
                    draft=TraceDraft(
                        operational={
                            "mode": mode,
                            "regulated_claim_hard_refusal": True,
                            "regulated_mode": True,
                        },
                        input=self._input_section(request),
                        output={"answer": escalation.message, "confidence": 0.0},
                        llm=llm_trace,
                        safety={"claim_failures": claim_failures},
                    ),
                )
            answer = regulated_result.answer
            citation_result = enforce_citations(
                answer,
                citation_context,
                effective.source_whitelist,
            )
            answer = citation_result.answer

        answer, disclaimer_ids = inject_disclaimers(
            answer,
            effective.disclaimers,
            regulated_mode=effective.regulated_mode,
            locale=effective.locale,
            crisis_path=False,
        )
        answer, sanitized_patterns = sanitize_output(
            answer,
            effective.guardrails,
            effective.compiled,
        )

        confidence = compute_retrieval_confidence(
            docs,
            citation_count=len(citation_result.valid_citations),
        )
        operational = {
            "mode": mode,
            "retrieved_count": len(docs),
            "citation_count": len(citation_result.valid_citations),
            "regulated_mode": effective.regulated_mode,
            "disclaimer_ids": disclaimer_ids,
            "output_sanitized": bool(sanitized_patterns),
        }
        if dense_skip_reason:
            operational["dense_skip_reason"] = dense_skip_reason
        return self._finalize_response(
            request=request,
            privacy_cfg=privacy_cfg,
            started_at=started_at,
            answer=answer,
            sources=citation_result.public_sources,
            confidence=round(confidence, 3),
            requires_human=False,
            escalation=None,
            draft=TraceDraft(
                operational=operational,
                input=self._input_section(request),
                output={"answer": answer, "confidence": round(confidence, 3)},
                llm=llm_trace,
                safety={
                    "claim_failures": claim_failures,
                    "stripped_markers": citation_result.stripped_citations,
                    "stripped_urls": citation_result.stripped_urls,
                },
            ),
        )

    def _finalize_response(
        self,
        *,
        request: ChatRequest,
        privacy_cfg: dict,
        answer: str,
        sources,
        confidence: float,
        requires_human: bool,
        escalation: Escalation | None,
        draft: TraceDraft,
        started_at: float | None = None,
    ) -> ChatResponse:
        if started_at is not None:
            draft.operational["latency_ms"] = {
                "total": int((perf_counter() - started_at) * 1000),
            }
        context = PrivacyContext(
            client_id=request.client_id,
            user_id=request.user_id,
            session_id=request.session_id,
            stack_profile=self._stack_profile,
        )
        gated = gate_trace(draft, privacy_cfg, context)
        privacy = normalize_privacy(privacy_cfg)
        privacy_safe_log("chat.completed", gated.log_payload)
        self._metrics_store.record_chat(context.client_id, gated.storable_trace)
        if should_persist_trace(privacy):
            self._trace_store.save(TraceRecord.from_gated(gated=gated, context=context))
        return ChatResponse(
            answer=answer,
            sources=sources,
            confidence=confidence,
            requires_human=requires_human,
            escalation=escalation,
            trace_id=gated.trace_id,
            trace=gated.api_trace,
            session_id=request.session_id,
        )

    def _finalize_fallback_response(
        self,
        *,
        request: ChatRequest,
        privacy_cfg: dict,
        started_at: float,
        llm_outcome: LLMOutcome,
        effective,
        mode: str,
        docs,
        dense_skip_reason: str | None,
        llm_trace: dict,
        llm_config: dict,
    ) -> ChatResponse:
        answer = llm_outcome.text
        blocked_cfg = llm_config.get("blocked_content") or {}
        escalation = None
        requires_human = False
        if llm_outcome.fallback_used:
            esc_type = str(blocked_cfg.get("escalation_type") or "provider_blocked")
            requires_human = bool(blocked_cfg.get("requires_human", False))
            escalation = Escalation(type=esc_type, message=answer)

        if effective.regulated_mode:
            answer, disclaimer_ids = inject_disclaimers(
                answer,
                effective.disclaimers,
                regulated_mode=True,
                locale=effective.locale,
                crisis_path=False,
            )
        else:
            disclaimer_ids = []

        answer, sanitized_patterns = sanitize_output(
            answer,
            effective.guardrails,
            effective.compiled,
        )

        return self._finalize_response(
            request=request,
            privacy_cfg=privacy_cfg,
            started_at=started_at,
            answer=answer,
            sources=[],
            confidence=0.0,
            requires_human=requires_human,
            escalation=escalation,
            draft=TraceDraft(
                operational={
                    "mode": mode,
                    "retrieved_count": len(docs),
                    "fallback_used": llm_outcome.fallback_used,
                    "dev_placeholder": llm_outcome.dev_placeholder,
                    "llm_skipped_citation_pipeline": True,
                    "disclaimer_ids": disclaimer_ids,
                    "output_sanitized": bool(sanitized_patterns),
                    "dense_skip_reason": dense_skip_reason,
                },
                input=self._input_section(request),
                output={"answer": answer, "confidence": 0.0},
                llm=llm_trace,
            ),
        )

    def _input_section(self, request: ChatRequest) -> dict:
        payload = {
            "original_message": request.message,
            "history": [{"role": m.role, "content": m.content} for m in request.history],
        }
        if request.effective_message and request.effective_message != request.message:
            payload["rewritten_query"] = request.effective_message
            payload["rewrite_reason"] = request.rewrite_reason or "none"
            payload["is_follow_up"] = request.is_follow_up
        return payload

    def _call_llm(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        llm_config: dict,
    ) -> LLMOutcome:
        if hasattr(self._llm_provider, "generate_with_outcome"):
            return self._llm_provider.generate_with_outcome(
                system_prompt,
                messages,
                llm_config=llm_config,
            )
        text = self._llm_provider.generate(
            system_prompt,
            messages,
            model=self._default_model,
            temperature=float((llm_config.get("defaults") or {}).get("temperature", 0.2)),
        )
        return LLMOutcome(
            text=text,
            model_used=self._default_model or "legacy",
            provider="legacy",
        )

    @staticmethod
    def _llm_trace_from_outcome(outcome: LLMOutcome) -> dict:
        return {
            "model_used": outcome.model_used,
            "provider": outcome.provider,
            "blocked": outcome.blocked,
            "block_reason": outcome.block_reason,
            "fallback_used": outcome.fallback_used,
            "dev_placeholder": outcome.dev_placeholder,
            "attempts": outcome.attempts,
        }

    def _build_messages(self, message: str, history: List, citation_context) -> List[Dict[str, str]]:
        context = format_numbered_context(citation_context)
        payload: List[Dict[str, str]] = []
        for m in history[-8:]:
            payload.append({"role": m.role, "content": m.content})
        payload.append({"role": "user", "content": f"{context}\n\nQuestion:\n{message}"})
        return payload
