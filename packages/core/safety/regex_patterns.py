from __future__ import annotations

import re
from typing import Any

from packages.core.config.models import ConfigValidationError

MAX_PATTERN_LENGTH = 500


def compile_pattern_list(
    patterns: list[Any],
    *,
    context: str,
) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for raw in patterns:
        pattern = str(raw).strip()
        if not pattern:
            continue
        if len(pattern) > MAX_PATTERN_LENGTH:
            raise ConfigValidationError(
                f"{context}: pattern exceeds max length ({MAX_PATTERN_LENGTH}): {pattern[:80]!r}..."
            )
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            raise ConfigValidationError(f"{context}: invalid regex {pattern!r}: {exc}") from exc
    return compiled
