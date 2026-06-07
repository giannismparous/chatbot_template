from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any

from packages.core.config.models import ConfigValidationError, MergedTenantConfig

VALID_MODES = frozenset({"standard", "anonymized", "aggregate_only", "do_not_log"})


@dataclass
class PrivacyContext:
    client_id: str
    user_id: str | None = None
    session_id: str | None = None
    stack_profile: str = "local"


@dataclass
class EffectivePrivacy:
    mode: str
    storage: dict[str, bool]
    persist_traces: bool
    pii_enabled: bool
    replacement: str
    detectors: dict[str, bool]
    hash_user_id: bool
    hash_salt_env: str
    expose_operational_trace: bool
    expose_debug_trace_in_api: bool
    retention_days: int


@dataclass
class TraceDraft:
    operational: dict[str, Any] = field(default_factory=dict)
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    retrieval: dict[str, Any] | None = None
    llm: dict[str, Any] | None = None
    safety: dict[str, Any] | None = None


@dataclass
class GatedTrace:
    trace_id: str
    privacy_mode: str
    api_trace: dict[str, Any]
    storable_trace: dict[str, Any]
    log_payload: dict[str, Any]


def validate_privacy_config(merged: MergedTenantConfig) -> None:
    privacy = merged.privacy or {}
    mode = str(privacy.get("mode") or "standard").strip().lower()
    if mode not in VALID_MODES:
        raise ConfigValidationError(
            f"Client {merged.client_id!r}: invalid privacy.mode {mode!r}"
        )
    retention = privacy.get("retention_days", 30)
    try:
        retention_val = int(retention)
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError(
            f"Client {merged.client_id!r}: privacy.retention_days must be an integer"
        ) from exc
    if not 1 <= retention_val <= 3650:
        raise ConfigValidationError(
            f"Client {merged.client_id!r}: privacy.retention_days must be between 1 and 3650"
        )


def normalize_privacy(privacy: dict[str, Any]) -> EffectivePrivacy:
    mode = str(privacy.get("mode") or "standard").strip().lower()
    if mode not in VALID_MODES:
        mode = "standard"

    storage_cfg = dict(privacy.get("storage") or {})
    persist_traces = bool(storage_cfg.get("persist_traces", False))
    storage = {
        "store_raw_messages": bool(
            storage_cfg.get(
                "store_raw_messages",
                privacy.get("store_raw_messages", True),
            )
        ),
        "store_rewritten_query": bool(
            storage_cfg.get(
                "store_rewritten_query",
                privacy.get("store_rewritten_query", True),
            )
        ),
        "store_answer": bool(storage_cfg.get("store_answer", True)),
        "store_history": bool(storage_cfg.get("store_history", True)),
        "store_retrieval_detail": bool(storage_cfg.get("store_retrieval_detail", True)),
        "store_llm_detail": bool(storage_cfg.get("store_llm_detail", True)),
    }

    if mode in {"aggregate_only", "do_not_log"}:
        storage["store_raw_messages"] = False
        storage["store_rewritten_query"] = False
        storage["store_answer"] = False
        storage["store_history"] = False
        storage["store_retrieval_detail"] = False
        storage["store_llm_detail"] = False

    pii_cfg = privacy.get("pii") or {}
    detectors_cfg = dict(pii_cfg.get("detectors") or {})
    detectors = {
        "email": bool(detectors_cfg.get("email", True)),
        "phone": bool(detectors_cfg.get("phone", True)),
        "credit_card": bool(detectors_cfg.get("credit_card", True)),
        "amka": bool(detectors_cfg.get("amka", True)),
        "ssn": bool(detectors_cfg.get("ssn", True)),
        "iban": bool(detectors_cfg.get("iban", True)),
        "address_heuristic": bool(detectors_cfg.get("address_heuristic", False)),
    }

    identity = privacy.get("identity") or {}
    hash_user_id = bool(identity.get("hash_user_id", False))
    if mode in {"anonymized", "aggregate_only"}:
        hash_user_id = True

    ephemeral = privacy.get("ephemeral") or {}
    pii_enabled = bool(pii_cfg.get("redaction_enabled", privacy.get("pii_redaction_enabled", True)))
    if mode == "anonymized":
        pii_enabled = True

    return EffectivePrivacy(
        mode=mode,
        storage=storage,
        persist_traces=persist_traces,
        pii_enabled=pii_enabled,
        replacement=str(pii_cfg.get("replacement") or "[REDACTED]"),
        detectors=detectors,
        hash_user_id=hash_user_id,
        hash_salt_env=str(identity.get("hash_salt_env") or "PRIVACY_HASH_SALT"),
        expose_operational_trace=bool(ephemeral.get("expose_operational_trace", True)),
        expose_debug_trace_in_api=bool(ephemeral.get("expose_debug_trace_in_api", False)),
        retention_days=int(privacy.get("retention_days", 30)),
    )


def hash_user_id(
    user_id: str,
    *,
    client_id: str,
    salt_env: str,
) -> str:
    salt = os.getenv(salt_env, "").strip() or "local-dev-salt"
    digest = hashlib.sha256(f"{salt}:{client_id}:{user_id}".encode("utf-8")).hexdigest()
    return digest[:16]
