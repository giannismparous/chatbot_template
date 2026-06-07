from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.dependencies import container
from apps.api.dependencies.config_http import ensure_tenant_config
from apps.api.dependencies.tenant import enforce_path_client_id, require_widget_tenant
from packages.core.tenant.context import TenantContext

router = APIRouter(prefix="/v1", tags=["config"])


@router.get("/theme/{client_id}")
def get_theme(
    client_id: str,
    tenant: TenantContext = Depends(require_widget_tenant),
) -> dict:
    enforce_path_client_id(client_id, tenant)
    ensure_tenant_config(tenant.client_id)
    return container.THEMES.get_theme(tenant.client_id)


@router.get("/config/public/{client_id}")
def get_public_config(
    client_id: str,
    tenant: TenantContext = Depends(require_widget_tenant),
) -> dict:
    enforce_path_client_id(client_id, tenant)
    ensure_tenant_config(tenant.client_id)
    return container.get_public_client_config(tenant.client_id)
