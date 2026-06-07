"""Privacy modes, PII redaction, and trace gating."""

from packages.core.privacy.config import (
    PrivacyContext,
    TraceDraft,
    normalize_privacy,
    validate_privacy_config,
)
from packages.core.privacy.logging import privacy_safe_log
from packages.core.privacy.processor import gate_trace
from packages.core.privacy.redactor import redact_structure, redact_text

__all__ = [
    "PrivacyContext",
    "TraceDraft",
    "gate_trace",
    "normalize_privacy",
    "privacy_safe_log",
    "redact_structure",
    "redact_text",
    "validate_privacy_config",
]
