from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Sequence, TypeVar

T = TypeVar("T")


class EmbeddingRateLimitError(Exception):
    pass


class EmbeddingQuotaError(Exception):
    pass


@dataclass
class EmbeddingKeyPool:
    keys: list[str]
    _index: int = 0

    @classmethod
    def from_env(cls) -> EmbeddingKeyPool:
        keys_raw = os.getenv("GEMINI_API_KEYS", "").strip()
        keys = [k.strip() for k in keys_raw.split(",") if k.strip()]
        primary = os.getenv("GEMINI_API_KEY", "").strip()
        if primary and primary not in keys:
            keys.insert(0, primary)
        elif primary and not keys:
            keys = [primary]
        if not keys:
            raise RuntimeError("No Gemini API keys configured (GEMINI_API_KEY or GEMINI_API_KEYS)")
        return cls(keys=keys)

    @property
    def current_key(self) -> str:
        return self.keys[self._index]

    def rotate(self) -> str:
        if len(self.keys) <= 1:
            return self.current_key
        self._index = (self._index + 1) % len(self.keys)
        return self.current_key

    def call_with_retry(
        self,
        operation: Callable[[str], T],
        *,
        max_retries: int,
        backoff_base_ms: int,
        backoff_max_ms: int,
    ) -> T:
        attempts = 0
        key_rotations = 0
        delay_ms = backoff_base_ms
        last_error: Exception | None = None

        while attempts <= max_retries:
            try:
                return operation(self.current_key)
            except EmbeddingQuotaError as exc:
                last_error = exc
                key_rotations += 1
                if key_rotations >= len(self.keys):
                    raise
                self.rotate()
                attempts += 1
            except EmbeddingRateLimitError as exc:
                last_error = exc
                if attempts >= max_retries:
                    raise
                time.sleep(min(delay_ms, backoff_max_ms) / 1000.0)
                delay_ms = min(delay_ms * 2, backoff_max_ms)
                attempts += 1
            except Exception:
                raise

        if last_error:
            raise last_error
        raise RuntimeError("Embedding retry loop exited unexpectedly")

    def embed_batch_with_retry(
        self,
        embed_one_key: Callable[[str, Sequence[str], str], list[list[float]]],
        texts: Sequence[str],
        *,
        model: str,
        max_retries: int,
        backoff_base_ms: int,
        backoff_max_ms: int,
    ) -> list[list[float]]:
        return self.call_with_retry(
            lambda key: embed_one_key(key, texts, model),
            max_retries=max_retries,
            backoff_base_ms=backoff_base_ms,
            backoff_max_ms=backoff_max_ms,
        )
