from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from apps.api.dependencies.admin_services import clients_root
from apps.api.dependencies.auth import require_admin_token
from apps.api.schemas_admin import (
    DriveSourceCreateRequest,
    DriveSourceDTO,
    DriveSourcesListDTO,
)
from packages.core.admin.roles import AdminContext
from packages.core.config.loader import TenantConfigLoader
from packages.core.drive_sources.config import add_drive_source, load_drive_sources, remove_drive_source
from packages.core.drive_sources.service import delete_drive_source_cache, list_drive_sources_with_status
from packages.core.drive_sources.validation import DriveSourceValidationError, validate_source_id
from packages.core.stack.factory import project_root
from packages.core.tenant.paths import client_config_dir, safe_client_id

router = APIRouter(
    prefix="/v1/admin/clients",
    tags=["admin-client-drive-sources"],
    dependencies=[Depends(require_admin_token)],
)


def _loader() -> TenantConfigLoader:
    root = project_root()
    return TenantConfigLoader(
        clients_root=clients_root(),
        domain_packs_root=root / "packages" / "domain_packs",
    )


@router.get("/{client_id}/drive-sources", response_model=DriveSourcesListDTO)
def get_drive_sources(
    client_id: str,
    admin: AdminContext = Depends(require_admin_token),
) -> DriveSourcesListDTO:
    _ = admin
    cid = safe_client_id(client_id)
    loader = _loader()
    config = load_drive_sources(client_config_dir(clients_root(), cid))
    payload = list_drive_sources_with_status(clients_root=clients_root(), client_id=cid, config_loader=loader)
    return DriveSourcesListDTO(
        defaults={
            "recursive": config.defaults.recursive,
            "include_shared_drives": config.defaults.include_shared_drives,
            "max_files_per_root": config.defaults.max_files_per_root,
        },
        sources=[DriveSourceDTO(**row) for row in payload["sources"]],
        credentials_configured=payload["credentials_configured"],
        service_account_email=payload.get("service_account_email"),
        credentials_error=payload.get("credentials_error"),
    )


@router.post("/{client_id}/drive-sources", response_model=DriveSourceDTO, status_code=status.HTTP_201_CREATED)
def create_drive_source(
    client_id: str,
    payload: DriveSourceCreateRequest,
    admin: AdminContext = Depends(require_admin_token),
) -> DriveSourceDTO:
    _ = admin
    cid = safe_client_id(client_id)
    loader = _loader()
    merged = loader.load(cid)
    config_dir = client_config_dir(clients_root(), cid)
    try:
        add_drive_source(
            config_dir,
            folder_id=payload.folder_id,
            title=payload.title,
            enabled=payload.enabled,
            recursive=payload.recursive,
            max_files=payload.max_files,
            source_id=payload.id,
            sync_settings=merged.ingestion,
        )
    except DriveSourceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    rows = list_drive_sources_with_status(clients_root=clients_root(), client_id=cid, config_loader=loader)
    created = next((row for row in rows["sources"] if row["folder_id"] == payload.folder_id.strip()), None)
    if created is None and payload.id:
        created = next((row for row in rows["sources"] if row["id"] == payload.id), None)
    if created is None:
        created = rows["sources"][-1] if rows["sources"] else None
    if created is None:
        raise HTTPException(status_code=500, detail="Failed to load created drive source.")
    return DriveSourceDTO(**created)


@router.delete("/{client_id}/drive-sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_drive_source(
    client_id: str,
    source_id: str,
    admin: AdminContext = Depends(require_admin_token),
) -> Response:
    _ = admin
    cid = safe_client_id(client_id)
    config_dir = client_config_dir(clients_root(), cid)
    try:
        sid = validate_source_id(source_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    try:
        remove_drive_source(config_dir, sid)
    except DriveSourceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    delete_drive_source_cache(clients_root(), cid, sid)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
