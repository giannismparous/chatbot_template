from __future__ import annotations

import re
from typing import Callable, Sequence

import google.generativeai as genai

from packages.adapters.embedding.key_pool import (
    EmbeddingKeyPool,
    EmbeddingQuotaError,
    EmbeddingRateLimitError,
)
from packages.core.ports.embedding_provider import EmbeddingProvider

EmbedFn = Callable[[str, Sequence[str], str], list[list[float]]]


def _classify_gemini_error(exc: Exception) -> Exception:
    message = str(exc).lower()
    if "429" in message or "rate limit" in message or "resource exhausted" in message:
        if "quota" in message or "billing" in message:
            return EmbeddingQuotaError(str(exc))
        return EmbeddingRateLimitError(str(exc))
    if "quota" in message or "billing" in message:
        return EmbeddingQuotaError(str(exc))
    return exc


def _default_embed_with_key(api_key: str, texts: Sequence[str], model: str) -> list[list[float]]:
    genai.configure(api_key=api_key)
    vectors: list[list[float]] = []
    for text in texts:
        res = genai.embed_content(model=model, content=text)
        emb = res.get("embedding", []) if isinstance(res, dict) else []
        vectors.append([float(v) for v in emb])
    return vectors


class GeminiEmbeddingAdapter(EmbeddingProvider):
    def __init__(
        self,
        key_pool: EmbeddingKeyPool,
        *,
        embed_fn: EmbedFn | None = None,
        max_retries: int = 3,
        backoff_base_ms: int = 500,
        backoff_max_ms: int = 30000,
        expected_dims: int | None = None,
    ) -> None:
        self._pool = key_pool
        self._embed_fn = embed_fn or _default_embed_with_key
        self._max_retries = max_retries
        self._backoff_base_ms = backoff_base_ms
        self._backoff_max_ms = backoff_max_ms
        self._expected_dims = expected_dims

    @classmethod
    def from_env(
        cls,
        *,
        max_retries: int = 3,
        backoff_base_ms: int = 500,
        backoff_max_ms: int = 30000,
        embed_fn: EmbedFn | None = None,
    ) -> GeminiEmbeddingAdapter:
        return cls(
            EmbeddingKeyPool.from_env(),
            embed_fn=embed_fn,
            max_retries=max_retries,
            backoff_base_ms=backoff_base_ms,
            backoff_max_ms=backoff_max_ms,
        )

    @property
    def expected_dims(self) -> int | None:
        return self._expected_dims

    def embed_texts(self, texts: Sequence[str], *, model: str) -> list[list[float]]:
        if not texts:
            return []

        def _operation(api_key: str) -> list[list[float]]:
            try:
                return self._embed_fn(api_key, texts, model)
            except (EmbeddingRateLimitError, EmbeddingQuotaError):
                raise
            except Exception as exc:
                raise _classify_gemini_error(exc) from exc

        return self._pool.embed_batch_with_retry(
            lambda key, batch, m: _operation(key),
            texts,
            model=model,
            max_retries=self._max_retries,
            backoff_base_ms=self._backoff_base_ms,
            backoff_max_ms=self._backoff_max_ms,
        )


def model_slug(model: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", model)
