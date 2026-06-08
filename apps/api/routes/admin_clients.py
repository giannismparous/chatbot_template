from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from apps.api.dependencies.admin_services import get_registry_service
from apps.api.dependencies.auth import require_admin_token
from apps.api.schemas_admin import (
    ClientCreateRequest,
    ClientCreateResponse,
    ClientSummaryDTO,
    WidgetKeyRotateRequest,
    WidgetKeyRotateResponse,
    WidgetKeySummaryDTO,
)
from packages.core.admin.registry import ClientAlreadyExistsError, ClientNotFoundError, ClientRegistryService
from packages.core.admin.roles import AdminContext
from packages.core.tenant.paths import safe_client_id

router = APIRouter(
    prefix="/v1/admin/clients",
    tags=["admin-clients"],
    dependencies=[Depends(require_admin_token)],
)


@router.post("", response_model=ClientCreateResponse, status_code=status.HTTP_201_CREATED)
def create_client(
    payload: ClientCreateRequest,
    admin: AdminContext = Depends(require_admin_token),
    registry: ClientRegistryService = Depends(get_registry_service),
) -> ClientCreateResponse:
    _ = admin
    try:
        safe_client_id(payload.client_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    try:
        result = registry.create_client(
            client_id=payload.client_id,
            display_name=payload.display_name,
            domain_pack=payload.domain_pack,
            allowed_origins=payload.allowed_origins,
            reveal_widget_key=payload.reveal_widget_key,
        )
    except ClientAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ClientCreateResponse(**result)


@router.get("", response_model=list[ClientSummaryDTO])
def list_clients(
    admin: AdminContext = Depends(require_admin_token),
    registry: ClientRegistryService = Depends(get_registry_service),
) -> list[ClientSummaryDTO]:
    _ = admin
    return [ClientSummaryDTO(**item) for item in registry.list_clients()]


@router.get("/{client_id}", response_model=ClientSummaryDTO)
def get_client(
    client_id: str,
    admin: AdminContext = Depends(require_admin_token),
    registry: ClientRegistryService = Depends(get_registry_service),
) -> ClientSummaryDTO:
    _ = admin
    try:
        return ClientSummaryDTO(**registry.get_client(client_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ClientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{client_id}/widget-keys", response_model=list[WidgetKeySummaryDTO])
def list_widget_keys(
    client_id: str,
    admin: AdminContext = Depends(require_admin_token),
    registry: ClientRegistryService = Depends(get_registry_service),
) -> list[WidgetKeySummaryDTO]:
    _ = admin
    try:
        keys = registry.list_widget_keys(client_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [WidgetKeySummaryDTO(**item) for item in keys]


@router.post("/{client_id}/widget-keys/rotate", response_model=WidgetKeyRotateResponse)
def rotate_widget_key(
    client_id: str,
    payload: WidgetKeyRotateRequest,
    admin: AdminContext = Depends(require_admin_token),
    registry: ClientRegistryService = Depends(get_registry_service),
) -> WidgetKeyRotateResponse:
    _ = admin
    try:
        result = registry.rotate_widget_key(
            client_id,
            allowed_origins=payload.allowed_origins or None,
            revoke_key_id=payload.revoke_key_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    return WidgetKeyRotateResponse(
        client_id=result.client_id,
        key_id=result.key_id,
        widget_key_prefix=result.widget_key_prefix,
        allowed_origins=list(result.allowed_origins),
        widget_key=result.widget_key,
        revoked_key_id=result.revoked_key_id,
    )


@router.post(
    "/{client_id}/widget-keys/{key_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def revoke_widget_key(
    client_id: str,
    key_id: str,
    admin: AdminContext = Depends(require_admin_token),
    registry: ClientRegistryService = Depends(get_registry_service),
) -> Response:
    _ = admin
    try:
        registry.revoke_widget_key(client_id, key_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
