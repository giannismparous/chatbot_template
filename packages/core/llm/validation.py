from __future__ import annotations

from typing import Any

from packages.core.config.models import ConfigValidationError, MergedTenantConfig

ALLOWED_RETRY_ON = frozenset({"rate_limit", "timeout", "server_error"})


def validate_llm_config(merged: MergedTenantConfig) -> None:
    llm = merged.llm or {}
    defaults = llm.get("defaults") or {}
    timeout = defaults.get("timeout_seconds")
    if timeout is not None:
        try:
            timeout_val = float(timeout)
        except (TypeError, ValueError) as exc:
            raise ConfigValidationError(
                f"Client {merged.client_id!r}: llm.defaults.timeout_seconds must be a number"
            ) from exc
        if not 5 <= timeout_val <= 120:
            raise ConfigValidationError(
                f"Client {merged.client_id!r}: llm.defaults.timeout_seconds must be between 5 and 120"
            )

    retry = llm.get("retry") or {}
    for item in retry.get("retry_on") or []:
        if str(item) not in ALLOWED_RETRY_ON:
            raise ConfigValidationError(
                f"Client {merged.client_id!r}: invalid llm.retry.retry_on value {item!r}"
            )

    for entry in llm.get("model_chain") or []:
        if not isinstance(entry, dict):
            raise ConfigValidationError(
                f"Client {merged.client_id!r}: llm.model_chain entries must be objects"
            )
        if entry.get("enabled", True) and not str(entry.get("model") or "").strip():
            raise ConfigValidationError(
                f"Client {merged.client_id!r}: enabled model_chain entry missing model"
            )


def resolve_model_chain(llm: dict[str, Any], *, default_model_env: str) -> list[dict[str, Any]]:
    chain = [
        entry
        for entry in (llm.get("model_chain") or [])
        if isinstance(entry, dict) and entry.get("enabled", True) and str(entry.get("model") or "").strip()
    ]
    if chain:
        return chain
    if default_model_env.strip():
        return [{"id": "env_default", "model": default_model_env.strip(), "enabled": True}]
    return []
