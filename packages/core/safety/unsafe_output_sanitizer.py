from __future__ import annotations

import re
from typing import Any

from packages.core.safety.models import CompiledSafetyPatterns


def sanitize_output(
    answer: str,
    guardrails: dict[str, Any],
    compiled: CompiledSafetyPatterns,
) -> tuple[str, list[str]]:
    sanitizer = guardrails.get("output_sanitizer") or {}
    if not sanitizer.get("enabled", True):
        return answer, []

    stripped_labels: list[str] = []
    result = answer

    for index, pattern in enumerate(compiled.output_strip_patterns):
        if pattern.search(result):
            stripped_labels.append(f"strip_pattern_{index}")
            result = pattern.sub("", result)

    result = re.sub(r"[ \t]{2,}", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip(), stripped_labels
