from __future__ import annotations

from fastapi import HTTPException, status

from packages.core.admin.config_keys import PLATFORM_ONLY_CONFIG_KEYS, resolve_config_key
from packages.core.admin.roles import AdminContext, AdminRole


class PermissionDenied(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def require_platform_admin(admin: AdminContext) -> None:
    if admin.role != AdminRole.PLATFORM_ADMIN:
        raise PermissionDenied("platform_admin required.")


def require_client_scope(admin: AdminContext, client_id: str) -> None:
    """Scaffold for future client_admin — not enabled in Phase 11."""
    if admin.role == AdminRole.PLATFORM_ADMIN:
        return
    if admin.role == AdminRole.CLIENT_ADMIN:
        if admin.client_id != client_id:
            raise PermissionDenied("client_admin may only access own client.")
        return
    raise PermissionDenied("Admin role not permitted.")


def assert_config_write_allowed(admin: AdminContext, client_id: str, config_key: str) -> str:
    """Return canonical config key if write is allowed for this admin role."""
    require_platform_admin(admin)
    require_client_scope(admin, client_id)
    canonical = resolve_config_key(config_key)
    if admin.role == AdminRole.CLIENT_ADMIN and canonical in PLATFORM_ONLY_CONFIG_KEYS:
        raise PermissionDenied(f"client_admin cannot write config key {canonical!r}.")
    return canonical


def assert_config_read_allowed(admin: AdminContext, client_id: str, config_key: str) -> str:
    require_platform_admin(admin)
    require_client_scope(admin, client_id)
    return resolve_config_key(config_key)
