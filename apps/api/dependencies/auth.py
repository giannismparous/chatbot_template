from __future__ import annotations

from fastapi import Depends

from apps.api.dependencies.tenant import require_platform_admin
from packages.core.admin.roles import AdminContext


def require_admin_token(admin: AdminContext = Depends(require_platform_admin)) -> AdminContext:
    """Backward-compatible admin dependency — returns platform admin context."""
    return admin
