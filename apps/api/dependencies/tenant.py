from __future__ import annotations

import os
from urllib.parse import urlparse

from fastapi import Header, HTTPException, Request, status

from apps.api.schemas import ChatRequestDTO
from apps.api.dependencies.stack import get_stack
from packages.core.admin.roles import AdminContext
from packages.core.ports.admin_auth import AdminAuthError
from packages.core.tenant.context import TenantContext
from packages.core.tenant.errors import OriginNotAllowedError, TenantAuthError, WidgetKeyNotFoundError
from packages.core.tenant.paths import safe_client_id


def _allow_insecure_client_id() -> bool:
    return os.getenv("ALLOW_INSECURE_CLIENT_ID", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _effective_origin(origin: str | None, referer: str | None) -> str | None:
    if origin and origin.strip():
        return origin.strip()
    if referer and referer.strip():
        parsed = urlparse(referer.strip())
        if parsed.scheme and parsed.netloc:
            port = f":{parsed.port}" if parsed.port else ""
            return f"{parsed.scheme}://{parsed.netloc}{port}"
    return None


def _auth_error_to_http(exc: TenantAuthError) -> HTTPException:
    if isinstance(exc, OriginNotAllowedError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


def resolve_widget_client_id(
    *,
    x_client_key: str | None,
    origin: str | None,
    referer: str | None,
    body_client_id: str | None = None,
) -> str:
    """Resolve client_id from x-client-key or insecure dev body hint."""
    if x_client_key and x_client_key.strip():
        stack = get_stack()
        try:
            return stack.auth_provider.resolve_widget_key(
                x_client_key.strip(),
                _effective_origin(origin, referer),
            )
        except TenantAuthError as exc:
            raise _auth_error_to_http(exc) from exc

    if _allow_insecure_client_id() and body_client_id:
        try:
            return safe_client_id(body_client_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid client_id.",
            ) from exc

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing x-client-key.",
    )


def enforce_client_id_match(resolved_client_id: str, body_client_id: str | None) -> None:
    if not body_client_id:
        return
    try:
        body_id = safe_client_id(body_client_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid client_id.",
        ) from exc
    if body_id != resolved_client_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="client_id does not match authenticated tenant.",
        )


def require_widget_tenant(
    request: Request,
    x_client_key: str | None = Header(default=None, alias="x-client-key"),
    origin: str | None = Header(default=None),
    referer: str | None = Header(default=None),
) -> TenantContext:
    body_client_id = request.path_params.get("client_id")
    client_id = resolve_widget_client_id(
        x_client_key=x_client_key,
        origin=origin,
        referer=referer,
        body_client_id=body_client_id,
    )
    return TenantContext(client_id=client_id)


def require_chat_tenant(
    payload: ChatRequestDTO,
    x_client_key: str | None = Header(default=None, alias="x-client-key"),
    origin: str | None = Header(default=None),
    referer: str | None = Header(default=None),
) -> TenantContext:
    client_id = resolve_widget_client_id(
        x_client_key=x_client_key,
        origin=origin,
        referer=referer,
        body_client_id=payload.client_id,
    )
    enforce_client_id_match(client_id, payload.client_id)
    return TenantContext(client_id=client_id)


def require_widget_tenant_for_body(
    body_client_id: str,
    x_client_key: str | None = Header(default=None, alias="x-client-key"),
    origin: str | None = Header(default=None),
    referer: str | None = Header(default=None),
) -> TenantContext:
    client_id = resolve_widget_client_id(
        x_client_key=x_client_key,
        origin=origin,
        referer=referer,
        body_client_id=body_client_id,
    )
    enforce_client_id_match(client_id, body_client_id)
    return TenantContext(client_id=client_id)


def require_platform_admin(
    x_admin_token: str | None = Header(default=None, alias="x-admin-token"),
) -> AdminContext:
    stack = get_stack()
    try:
        return stack.admin_auth_provider.resolve_admin(x_admin_token)
    except AdminAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


def enforce_path_client_id(path_client_id: str, tenant: TenantContext) -> None:
    try:
        path_id = safe_client_id(path_client_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid client_id.",
        ) from exc
    if path_id != tenant.client_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="client_id does not match authenticated tenant.",
        )
