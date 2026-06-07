from __future__ import annotations

import time
from typing import Any, Dict, Sequence

from packages.core.llm.errors import (
    LLMClientError,
    LLMQuotaError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
)
from packages.core.llm.key_pool import LLMKeyPool
from packages.core.llm.models import LLMOutcome
from packages.core.llm.validation import resolve_model_chain
from packages.core.ports.llm_backend import LLMBackend


class LLMOrchestrator:
    """Model chain, key rotation, retry/backoff, blocked-content fallback."""

    def __init__(
        self,
        backend: LLMBackend,
        key_pool: LLMKeyPool,
        *,
        stack_profile: str = "local",
        default_model_env: str = "",
    ) -> None:
        self._backend = backend
        self._key_pool = key_pool
        self._stack_profile = stack_profile
        self._default_model_env = default_model_env

    def generate(
        self,
        *,
        system_prompt: str,
        messages: Sequence[Dict[str, str]],
        llm_config: dict[str, Any],
    ) -> LLMOutcome:
        cfg = llm_config or {}
        defaults = cfg.get("defaults") or {}
        temperature = float(defaults.get("temperature", 0.2))
        timeout_seconds = float(defaults.get("timeout_seconds", 30))
        max_output_tokens = defaults.get("max_output_tokens")
        max_tokens = int(max_output_tokens) if max_output_tokens is not None else None

        retry_cfg = cfg.get("retry") or {}
        max_retries = int(retry_cfg.get("max_retries_per_model", 2))
        backoff_base_ms = int(retry_cfg.get("backoff_base_ms", 500))
        backoff_max_ms = int(retry_cfg.get("backoff_max_ms", 15000))
        retry_on = {str(v) for v in (retry_cfg.get("retry_on") or ["rate_limit", "timeout", "server_error"])}

        blocked_cfg = cfg.get("blocked_content") or {}
        try_next_model = bool(blocked_cfg.get("try_next_model", True))

        model_chain = resolve_model_chain(cfg, default_model_env=self._default_model_env)
        if not model_chain:
            return self._fallback_outcome(cfg, attempts=[], blocked=False)

        if not self._key_pool.has_keys:
            if self._dev_placeholder_allowed(cfg):
                return self._dev_placeholder_outcome(messages, cfg)
            return self._fallback_outcome(cfg, attempts=[], blocked=False)

        attempts_log: list[dict[str, Any]] = []
        primary_failed = False

        for model_entry in model_chain:
            if model_entry.get("fallback_only") and not primary_failed:
                continue

            model_name = str(model_entry["model"])
            model_blocked = False
            delay_ms = backoff_base_ms

            for attempt_idx in range(max_retries + 1):
                api_key = self._key_pool.next_available_key()
                if api_key is None:
                    return self._fallback_outcome(cfg, attempts=attempts_log, blocked=True)

                try:
                    result = self._backend.generate_once(
                        api_key=api_key,
                        model=model_name,
                        system_prompt=system_prompt,
                        messages=messages,
                        temperature=temperature,
                        timeout_seconds=timeout_seconds,
                        max_output_tokens=max_tokens,
                    )
                except LLMQuotaError as exc:
                    attempts_log.append(
                        self._attempt_record(model_name, attempt_idx, "quota", str(exc))
                    )
                    self._key_pool.mark_cooldown(api_key)
                    self._key_pool.rotate()
                    primary_failed = True
                    break
                except LLMRateLimitError as exc:
                    attempts_log.append(
                        self._attempt_record(model_name, attempt_idx, "rate_limit", str(exc))
                    )
                    if "rate_limit" not in retry_on or attempt_idx >= max_retries:
                        primary_failed = True
                        break
                    time.sleep(min(delay_ms, backoff_max_ms) / 1000.0)
                    delay_ms = min(delay_ms * 2, backoff_max_ms)
                    continue
                except LLMTimeoutError as exc:
                    attempts_log.append(
                        self._attempt_record(model_name, attempt_idx, "timeout", str(exc))
                    )
                    if "timeout" not in retry_on or attempt_idx >= max_retries:
                        primary_failed = True
                        break
                    time.sleep(min(delay_ms, backoff_max_ms) / 1000.0)
                    delay_ms = min(delay_ms * 2, backoff_max_ms)
                    continue
                except LLMServerError as exc:
                    attempts_log.append(
                        self._attempt_record(model_name, attempt_idx, "server_error", str(exc))
                    )
                    if "server_error" not in retry_on or attempt_idx >= max_retries:
                        primary_failed = True
                        break
                    time.sleep(min(delay_ms, backoff_max_ms) / 1000.0)
                    delay_ms = min(delay_ms * 2, backoff_max_ms)
                    continue
                except LLMClientError as exc:
                    attempts_log.append(
                        self._attempt_record(model_name, attempt_idx, "client_error", str(exc))
                    )
                    primary_failed = True
                    break
                except Exception as exc:
                    attempts_log.append(
                        self._attempt_record(model_name, attempt_idx, "error", str(exc))
                    )
                    primary_failed = True
                    break

                if result.blocked:
                    attempts_log.append(
                        {
                            **self._attempt_record(
                                model_name,
                                attempt_idx,
                                "blocked",
                                result.block_reason or "blocked",
                            ),
                            "block_reason": result.block_reason,
                        }
                    )
                    model_blocked = True
                    primary_failed = True
                    break

                text = (result.text or "").strip()
                if text:
                    return LLMOutcome(
                        text=text,
                        model_used=model_name,
                        provider=self._backend.provider_name,
                        blocked=False,
                        truncated=bool(result.truncated),
                        attempts=attempts_log,
                    )

                attempts_log.append(
                    self._attempt_record(model_name, attempt_idx, "empty_response", "empty")
                )
                primary_failed = True
                break

            if model_blocked and try_next_model:
                continue
            if model_blocked:
                break

        return self._fallback_outcome(cfg, attempts=attempts_log, blocked=True)

    def _dev_placeholder_allowed(self, llm_config: dict[str, Any]) -> bool:
        if self._stack_profile != "local":
            return False
        dev = llm_config.get("dev") or {}
        return bool(dev.get("allow_missing_key_placeholder", False))

    def _dev_placeholder_outcome(
        self,
        messages: Sequence[Dict[str, str]],
        llm_config: dict[str, Any],
    ) -> LLMOutcome:
        dev = llm_config.get("dev") or {}
        prefix = str(dev.get("placeholder_prefix") or "[DEV PLACEHOLDER]").strip()
        latest = messages[-1]["content"] if messages else ""
        snippet = latest[:180]
        return LLMOutcome(
            text=f"{prefix} Gemini key missing. Received: {snippet}",
            model_used="dev_placeholder",
            provider=self._backend.provider_name,
            dev_placeholder=True,
            attempts=[{"kind": "dev_placeholder"}],
        )

    def _fallback_outcome(
        self,
        llm_config: dict[str, Any],
        *,
        attempts: list[dict[str, Any]],
        blocked: bool,
    ) -> LLMOutcome:
        blocked_cfg = llm_config.get("blocked_content") or {}
        message = str(
            blocked_cfg.get("fallback_message")
            or "I couldn't generate a response for that question. Please rephrase or try again later."
        ).strip()
        return LLMOutcome(
            text=message,
            model_used="fallback",
            provider=self._backend.provider_name,
            blocked=blocked,
            block_reason="provider_blocked" if blocked else None,
            fallback_used=True,
            attempts=attempts,
        )

    @staticmethod
    def _attempt_record(model: str, attempt: int, kind: str, detail: str) -> dict[str, Any]:
        return {
            "model": model,
            "attempt": attempt,
            "kind": kind,
            "detail": detail[:200],
        }
