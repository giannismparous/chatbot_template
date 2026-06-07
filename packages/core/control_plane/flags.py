from __future__ import annotations

import os


def firestore_control_plane_enabled() -> bool:
    value = os.getenv("FIRESTORE_CONTROL_PLANE", "true").strip().lower()
    return value in {"1", "true", "yes", "on"}


def gcs_registry_fallback_enabled() -> bool:
    value = os.getenv("GCS_REGISTRY_FALLBACK", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}
