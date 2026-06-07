from __future__ import annotations

import copy
import re
from typing import Any

from packages.core.privacy.patterns import DETECTOR_PATTERNS


def redact_text(text: str, *, detectors: dict[str, bool], replacement: str) -> str:
    if not text or not detectors:
        return text
    result = text
    for name, enabled in detectors.items():
        if not enabled:
            continue
        pattern = DETECTOR_PATTERNS.get(name)
        if pattern is None:
            continue
        if name == "credit_card":
            result = _redact_credit_cards(result, replacement)
        else:
            result = pattern.sub(replacement, result)
    return result


def _redact_credit_cards(text: str, replacement: str) -> str:
    pattern = DETECTOR_PATTERNS["credit_card"]

    def _replace(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) < 13 or len(digits) > 19:
            return match.group(0)
        if not _luhn_valid(digits):
            return match.group(0)
        return replacement

    return pattern.sub(_replace, text)


def _luhn_valid(number: str) -> bool:
    total = 0
    reverse = number[::-1]
    for index, char in enumerate(reverse):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def redact_structure(
    value: Any,
    *,
    detectors: dict[str, bool],
    replacement: str,
) -> Any:
    if isinstance(value, str):
        return redact_text(value, detectors=detectors, replacement=replacement)
    if isinstance(value, list):
        return [redact_structure(item, detectors=detectors, replacement=replacement) for item in value]
    if isinstance(value, dict):
        return {
            key: redact_structure(item, detectors=detectors, replacement=replacement)
            for key, item in value.items()
        }
    return copy.deepcopy(value)
