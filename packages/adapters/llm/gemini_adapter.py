from __future__ import annotations

import concurrent.futures
from typing import Callable, Dict, Sequence

import google.generativeai as genai

from packages.core.llm.errors import (
    LLMClientError,
    LLMQuotaError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
)
from packages.core.ports.llm_backend import LLMBackend, LLMGenerateResult

GenerateFn = Callable[..., LLMGenerateResult]


def classify_gemini_error(exc: Exception) -> Exception:
    message = str(exc).lower()
    if "prohibited_content" in message or "block_reason" in message or "safety" in message:
        return LLMClientError("blocked")
    if "429" in message or "rate limit" in message or "resource exhausted" in message:
        if "quota" in message or "billing" in message:
            return LLMQuotaError(str(exc))
        return LLMRateLimitError(str(exc))
    if "quota" in message or "billing" in message:
        return LLMQuotaError(str(exc))
    if "timeout" in message or "timed out" in message or "deadline" in message:
        return LLMTimeoutError(str(exc))
    if any(token in message for token in ("500", "502", "503", "504", "internal", "unavailable")):
        return LLMServerError(str(exc))
    if any(token in message for token in ("400", "401", "403", "404", "invalid")):
        return LLMClientError(str(exc))
    return exc


def _extract_finish_reason(response: object) -> str | None:
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        finish_reason = getattr(candidate, "finish_reason", None)
        if finish_reason is not None:
            return str(finish_reason)
    return None


def _is_truncated_finish_reason(finish_reason: str | None) -> bool:
    if not finish_reason:
        return False
    normalized = finish_reason.upper()
    return "MAX" in normalized and "TOKEN" in normalized


def _extract_blocked_reason(response: object) -> str | None:
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None:
        block_reason = getattr(feedback, "block_reason", None)
        if block_reason:
            return str(block_reason)
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        finish_reason = getattr(candidate, "finish_reason", None)
        if finish_reason is not None and str(finish_reason) not in {"STOP", "1", "FinishReason.STOP"}:
            return str(finish_reason)
        safety_ratings = getattr(candidate, "safety_ratings", None)
        if safety_ratings:
            return "safety"
    return None


def _default_gemini_generate(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    messages: Sequence[Dict[str, str]],
    temperature: float,
    max_output_tokens: int | None,
) -> LLMGenerateResult:
    genai.configure(api_key=api_key)
    generation_config: dict = {"temperature": temperature}
    if max_output_tokens is not None:
        generation_config["max_output_tokens"] = max_output_tokens

    prompt_parts: list[str] = []
    if system_prompt.strip():
        prompt_parts.append(f"SYSTEM:\n{system_prompt.strip()}")
    prompt_parts.append("\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages))
    prompt = "\n\n".join(prompt_parts)

    try:
        model_client = genai.GenerativeModel(
            model_name=model,
            system_instruction=system_prompt,
            generation_config=generation_config,
        )
    except TypeError:
        model_client = genai.GenerativeModel(
            model_name=model,
            generation_config=generation_config,
        )

    response = model_client.generate_content(prompt)

    finish_reason = _extract_finish_reason(response)
    truncated = _is_truncated_finish_reason(finish_reason)
    block_reason = _extract_blocked_reason(response)
    text = (getattr(response, "text", None) or "").strip()
    if block_reason and not text:
        return LLMGenerateResult(text="", blocked=True, block_reason=block_reason, truncated=truncated)
    if block_reason and text:
        return LLMGenerateResult(text=text, blocked=False, truncated=truncated)
    if not text and block_reason is None:
        block_reason = _extract_blocked_reason(response)
        if block_reason:
            return LLMGenerateResult(text="", blocked=True, block_reason=block_reason, truncated=truncated)
    return LLMGenerateResult(text=text, blocked=False, truncated=truncated)


class GeminiLLMBackend(LLMBackend):
    def __init__(self, *, generate_fn: GenerateFn | None = None) -> None:
        self._generate_fn = generate_fn or _default_gemini_generate

    @property
    def provider_name(self) -> str:
        return "gemini"

    def generate_once(
        self,
        *,
        api_key: str,
        model: str,
        system_prompt: str,
        messages: Sequence[Dict[str, str]],
        temperature: float,
        timeout_seconds: float,
        max_output_tokens: int | None = None,
    ) -> LLMGenerateResult:
        if not api_key:
            raise LLMClientError("missing_api_key")

        def _run() -> LLMGenerateResult:
            try:
                return self._generate_fn(
                    api_key=api_key,
                    model=model,
                    system_prompt=system_prompt,
                    messages=messages,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
            except Exception as exc:
                classified = classify_gemini_error(exc)
                if isinstance(classified, LLMClientError) and classified.args == ("blocked",):
                    return LLMGenerateResult(text="", blocked=True, block_reason="PROHIBITED_CONTENT")
                raise classified from exc

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run)
            try:
                return future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError as exc:
                raise LLMTimeoutError(f"LLM request timed out after {timeout_seconds}s") from exc


# Backward-compatible alias used by embedding-era imports
class GeminiAdapter(GeminiLLMBackend):
    """Legacy name — prefer GeminiLLMBackend for new code."""

    def __init__(self, api_key: str | None = None, *, generate_fn: GenerateFn | None = None) -> None:
        super().__init__(generate_fn=generate_fn)
        self._legacy_api_key = api_key

    def generate(
        self,
        system_prompt: str,
        messages: Sequence[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
    ) -> str:
        import os

        api_key = self._legacy_api_key or os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            latest = messages[-1]["content"] if messages else ""
            return f"[DEV PLACEHOLDER] Gemini key missing. Received: {latest[:180]}"
        result = self.generate_once(
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            messages=messages,
            temperature=temperature,
            timeout_seconds=30.0,
        )
        if result.blocked:
            return ""
        return result.text

    def embed_texts(self, texts: Sequence[str], model: str = "gemini-embedding-001") -> list[list[float]]:
        import os

        api_key = self._legacy_api_key or os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError("Gemini API key is missing.")
        genai.configure(api_key=api_key)
        vectors: list[list[float]] = []
        for text in texts:
            res = genai.embed_content(model=model, content=text)
            emb = res.get("embedding", []) if isinstance(res, dict) else []
            vectors.append([float(v) for v in emb])
        return vectors
