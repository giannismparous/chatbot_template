from __future__ import annotations

import copy
import uuid
from typing import Any

from packages.core.privacy.config import (
    EffectivePrivacy,
    GatedTrace,
    PrivacyContext,
    TraceDraft,
    hash_user_id,
    normalize_privacy,
)
from packages.core.privacy.redactor import redact_structure

OPERATIONAL_LLM_KEYS = frozenset(
    {"model_used", "provider", "blocked", "fallback_used", "dev_placeholder", "attempts_count"}
)


def gate_trace(
    draft: TraceDraft,
    privacy_raw: dict[str, Any],
    context: PrivacyContext,
) -> GatedTrace:
    privacy = normalize_privacy(privacy_raw)
    trace_id = f"tr_{uuid.uuid4().hex[:12]}"

    working = TraceDraft(
        operational=copy.deepcopy(draft.operational),
        input=copy.deepcopy(draft.input) if draft.input else None,
        output=copy.deepcopy(draft.output) if draft.output else None,
        retrieval=copy.deepcopy(draft.retrieval) if draft.retrieval else None,
        llm=copy.deepcopy(draft.llm) if draft.llm else None,
        safety=copy.deepcopy(draft.safety) if draft.safety else None,
    )

    if privacy.pii_enabled:
        working = _redact_draft(working, privacy)

    if context.user_id and privacy.hash_user_id:
        working.operational["user_id_hash"] = hash_user_id(
            context.user_id,
            client_id=context.client_id,
            salt_env=privacy.hash_salt_env,
        )
    elif context.user_id and privacy.mode == "standard" and privacy.storage.get("store_raw_messages"):
        working.operational["user_id"] = context.user_id

    storable = _build_storable_trace(working, privacy, trace_id)
    api_trace = _build_api_trace(storable, privacy, context)
    log_payload = _build_log_payload(storable, privacy, trace_id, context)

    return GatedTrace(
        trace_id=trace_id,
        privacy_mode=privacy.mode,
        api_trace=api_trace,
        storable_trace=storable,
        log_payload=log_payload,
    )


def _redact_draft(draft: TraceDraft, privacy: EffectivePrivacy) -> TraceDraft:
    kwargs = {"detectors": privacy.detectors, "replacement": privacy.replacement}
    if draft.input is not None:
        draft.input = redact_structure(draft.input, **kwargs)
    if draft.output is not None:
        draft.output = redact_structure(draft.output, **kwargs)
    if draft.retrieval is not None:
        draft.retrieval = redact_structure(draft.retrieval, **kwargs)
    if draft.llm is not None:
        draft.llm = redact_structure(draft.llm, **kwargs)
    if draft.safety is not None:
        draft.safety = redact_structure(draft.safety, **kwargs)
    draft.operational = redact_structure(draft.operational, **kwargs)
    return draft


def _build_storable_trace(draft: TraceDraft, privacy: EffectivePrivacy, trace_id: str) -> dict[str, Any]:
    storable: dict[str, Any] = {
        "trace_id": trace_id,
        "privacy_mode": privacy.mode,
        **copy.deepcopy(draft.operational),
    }

    if privacy.mode == "do_not_log":
        return _minimal_metadata(storable)

    if privacy.mode == "aggregate_only":
        return _aggregate_metadata(storable, draft)

    if draft.input and _storage_allows(privacy, "store_raw_messages", "store_history"):
        input_payload = {}
        if privacy.storage.get("store_raw_messages") and draft.input.get("original_message") is not None:
            input_payload["original_message"] = draft.input.get("original_message")
        if privacy.storage.get("store_rewritten_query") and draft.input.get("rewritten_query") is not None:
            input_payload["rewritten_query"] = draft.input.get("rewritten_query")
        if privacy.storage.get("store_history") and draft.input.get("history") is not None:
            input_payload["history"] = draft.input.get("history")
        if input_payload:
            storable["input"] = input_payload

    if draft.output and privacy.storage.get("store_answer"):
        output_payload = {}
        if draft.output.get("answer") is not None:
            output_payload["answer"] = draft.output.get("answer")
        if draft.output.get("confidence") is not None:
            output_payload["confidence"] = draft.output.get("confidence")
        if output_payload:
            storable["output"] = output_payload

    if draft.retrieval and privacy.storage.get("store_retrieval_detail"):
        storable["retrieval"] = _strip_chunk_text(draft.retrieval)

    if draft.llm and privacy.storage.get("store_llm_detail"):
        storable["llm"] = _sanitize_llm_detail(draft.llm)

    if draft.safety:
        storable["safety"] = copy.deepcopy(draft.safety)

    if draft.output and draft.output.get("confidence") is not None:
        storable["confidence"] = draft.output.get("confidence")

    return storable


def _minimal_metadata(storable: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "trace_id",
        "privacy_mode",
        "mode",
        "no_context",
        "crisis_hit",
        "input_blocked",
        "human_handoff",
        "llm_skipped",
        "retrieval_skipped",
        "fallback_used",
        "regulated_claim_hard_refusal",
        "user_id_hash",
    }
    return {key: value for key, value in storable.items() if key in allowed}


def _aggregate_metadata(storable: dict[str, Any], draft: TraceDraft) -> dict[str, Any]:
    result = _minimal_metadata(storable)
    for key in (
        "retrieved_count",
        "citation_count",
        "confidence",
        "regulated_mode",
        "output_sanitized",
        "dev_placeholder",
        "llm_skipped_citation_pipeline",
        "latency_ms",
    ):
        if key in storable:
            result[key] = storable[key]
    if "confidence" not in result and draft.output and draft.output.get("confidence") is not None:
        result["confidence"] = draft.output.get("confidence")
    if draft.llm:
        result["llm"] = {
            "model_used": draft.llm.get("model_used"),
            "fallback_used": draft.llm.get("fallback_used"),
            "attempts_count": _attempts_count(draft.llm),
        }
    return result


def _build_api_trace(
    storable: dict[str, Any],
    privacy: EffectivePrivacy,
    context: PrivacyContext,
) -> dict[str, Any]:
    debug_allowed = (
        context.stack_profile == "local"
        and privacy.expose_debug_trace_in_api
        and privacy.mode in {"standard", "anonymized"}
    )
    if debug_allowed:
        return copy.deepcopy(storable)

    if not privacy.expose_operational_trace:
        return {"trace_id": storable.get("trace_id"), "privacy_mode": privacy.mode}

    return _operational_only(storable)


def _operational_only(storable: dict[str, Any]) -> dict[str, Any]:
    blocked_keys = {
        "input",
        "output",
        "retrieval",
        "safety",
        "original_message",
        "history",
        "answer",
        "claim_failures",
        "stripped_urls",
        "block_reason",
        "attempts",
    }
    api: dict[str, Any] = {}
    for key, value in storable.items():
        if key in blocked_keys:
            continue
        if key == "llm" and isinstance(value, dict):
            api["llm"] = {
                k: value.get(k)
                for k in OPERATIONAL_LLM_KEYS
                if k in value or k == "attempts_count"
            }
            if "attempts" in value and "attempts_count" not in api["llm"]:
                api["llm"]["attempts_count"] = _attempts_count(value)
            continue
        api[key] = copy.deepcopy(value)
    return api


def _build_log_payload(
    storable: dict[str, Any],
    privacy: EffectivePrivacy,
    trace_id: str,
    context: PrivacyContext,
) -> dict[str, Any]:
    if privacy.mode == "do_not_log":
        return {
            "trace_id": trace_id,
            "client_id": context.client_id,
            "privacy_mode": privacy.mode,
            "event": "chat.completed",
        }
    if privacy.mode == "aggregate_only":
        payload = _operational_only(storable)
        payload["client_id"] = context.client_id
        payload["event"] = "chat.completed"
        return payload
    payload = copy.deepcopy(storable)
    payload["client_id"] = context.client_id
    payload["event"] = "chat.completed"
    return payload


def _storage_allows(privacy: EffectivePrivacy, *keys: str) -> bool:
    return any(privacy.storage.get(key) for key in keys)


def _strip_chunk_text(retrieval: dict[str, Any]) -> dict[str, Any]:
    cleaned = copy.deepcopy(retrieval)
    for key in ("selected", "chunks", "rejected"):
        items = cleaned.get(key)
        if not isinstance(items, list):
            continue
        cleaned[key] = [
            {k: v for k, v in item.items() if k not in {"text", "content", "body"}}
            if isinstance(item, dict)
            else item
            for item in items
        ]
    return cleaned


def _sanitize_llm_detail(llm: dict[str, Any]) -> dict[str, Any]:
    cleaned = copy.deepcopy(llm)
    cleaned.pop("block_reason", None)
    attempts = cleaned.get("attempts")
    if isinstance(attempts, list):
        cleaned["attempts_count"] = len(attempts)
        cleaned["attempts"] = [{"kind": a.get("kind"), "model": a.get("model")} for a in attempts if isinstance(a, dict)]
    return cleaned


def _attempts_count(llm: dict[str, Any]) -> int:
    attempts = llm.get("attempts")
    if isinstance(attempts, list):
        return len(attempts)
    return int(llm.get("attempts_count") or 0)
