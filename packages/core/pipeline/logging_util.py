from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def pipeline_log(message: str) -> None:
    line = f"[pipeline] {message}"
    print(line, flush=True)
    logger.info("%s", message)


def pipeline_version_label() -> str:
    for key in ("GIT_SHA", "K_REVISION", "BUILD_ID", "APP_VERSION"):
        value = os.getenv(key, "").strip()
        if value:
            return f"{key}={value}"
    return "version=unknown"
