from __future__ import annotations

from packages.core.privacy.config import EffectivePrivacy, hash_user_id
from packages.core.privacy.redactor import redact_structure


def session_content_allowed(privacy: EffectivePrivacy) -> bool:
    if privacy.mode in {"aggregate_only", "do_not_log"}:
        return False
    return bool(privacy.storage.get("store_history") or privacy.storage.get("store_raw_messages"))


def hash_session_user_id(user_id: str | None, *, client_id: str, privacy: EffectivePrivacy) -> str | None:
    if not user_id:
        return None
    if privacy.hash_user_id or privacy.mode in {"anonymized", "aggregate_only", "do_not_log"}:
        return hash_user_id(user_id, client_id=client_id, salt_env=privacy.hash_salt_env)
    return user_id


def redact_for_session_storage(text: str, privacy: EffectivePrivacy) -> str | None:
    if not session_content_allowed(privacy):
        return None
    if not text:
        return text
    if privacy.pii_enabled:
        redacted = redact_structure(
            {"content": text},
            detectors=privacy.detectors,
            replacement=privacy.replacement,
        )
        return str(redacted.get("content") or "")
    return text
