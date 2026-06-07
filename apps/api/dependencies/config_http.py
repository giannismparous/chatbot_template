from __future__ import annotations

from fastapi import HTTPException, status

from packages.core.config.models import ConfigValidationError


def ensure_tenant_config(client_id: str):
    """Load merged tenant config or raise HTTP 503 with a safe message."""
    from apps.api.dependencies import container

    try:
        return container.TENANT_CONFIG.load(client_id)
    except ConfigValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
