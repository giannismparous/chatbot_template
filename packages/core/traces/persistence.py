from __future__ import annotations

from packages.core.privacy.config import EffectivePrivacy


def should_persist_trace(privacy: EffectivePrivacy) -> bool:
    if not privacy.persist_traces:
        return False
    if privacy.mode == "do_not_log":
        return False
    return True
