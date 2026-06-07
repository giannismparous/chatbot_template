from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.dependencies.admin_services import get_config_service
from apps.api.dependencies.auth import require_admin_token
from apps.api.schemas_admin import ConfigGetResponse, ConfigPutRequest, ConfigPutResponse
from packages.core.admin.config_service import ConfigService
from packages.core.admin.permission_guard import assert_config_read_allowed, assert_config_write_allowed
from packages.core.admin.roles import AdminContext
from packages.core.config.models import ConfigValidationError

router = APIRouter(
    prefix="/v1/admin/clients",
    tags=["admin-client-config"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/{client_id}/config/{config_key}", response_model=ConfigGetResponse)
def get_client_config(
    client_id: str,
    config_key: str,
    admin: AdminContext = Depends(require_admin_token),
    config_service: ConfigService = Depends(get_config_service),
) -> ConfigGetResponse:
    try:
        canonical = assert_config_read_allowed(admin, client_id, config_key)
        data = config_service.get_config(client_id, canonical)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ConfigGetResponse(key=canonical, data=data)


@router.put("/{client_id}/config/{config_key}", response_model=ConfigPutResponse)
def put_client_config(
    client_id: str,
    config_key: str,
    payload: ConfigPutRequest,
    admin: AdminContext = Depends(require_admin_token),
    config_service: ConfigService = Depends(get_config_service),
) -> ConfigPutResponse:
    try:
        canonical = assert_config_write_allowed(admin, client_id, config_key)
        config_service.put_config(client_id, canonical, payload.data)
    except ConfigValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ConfigPutResponse(key=canonical)
