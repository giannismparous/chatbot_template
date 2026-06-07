from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field


@dataclass
class LLMKeyPool:
    keys: list[str]
    cooldown_seconds: float = 60.0
    _index: int = 0
    _cooldown_until: dict[int, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def from_env(
        cls,
        *,
        cooldown_seconds: float = 60.0,
        env_list_var: str = "GEMINI_API_KEYS",
        env_primary_var: str = "GEMINI_API_KEY",
    ) -> LLMKeyPool:
        keys_raw = os.getenv(env_list_var, "").strip()
        keys = [k.strip() for k in keys_raw.split(",") if k.strip()]
        primary = os.getenv(env_primary_var, "").strip()
        if primary and primary not in keys:
            keys.insert(0, primary)
        elif primary and not keys:
            keys = [primary]
        return cls(keys=keys, cooldown_seconds=cooldown_seconds)

    @property
    def has_keys(self) -> bool:
        return bool(self.keys)

    def mark_cooldown(self, key: str) -> None:
        with self._lock:
            try:
                idx = self.keys.index(key)
            except ValueError:
                idx = self._index
            self._cooldown_until[idx] = time.time() + self.cooldown_seconds

    def rotate(self) -> None:
        with self._lock:
            if len(self.keys) > 1:
                self._index = (self._index + 1) % len(self.keys)

    def next_available_key(self) -> str | None:
        with self._lock:
            if not self.keys:
                return None
            now = time.time()
            for _ in range(len(self.keys)):
                idx = self._index
                if self._cooldown_until.get(idx, 0.0) <= now:
                    return self.keys[idx]
                self._index = (self._index + 1) % len(self.keys)
            return None
