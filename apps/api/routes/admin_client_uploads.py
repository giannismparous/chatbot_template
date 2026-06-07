from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from apps.api.dependencies.admin_services import clients_root
from apps.api.dependencies.auth import require_admin_token
from apps.api.schemas_admin import (
    UploadCitationDTO,
    UploadCitationPutRequest,
    UploadEntryDTO,
    UploadListDTO,
    UploadResultDTO,
)
from packages.core.admin.citation_mapping import (
    load_client_whitelist,
    mapping_requires_reingest,
)
from packages.core.admin.roles import AdminContext
from packages.core.admin.upload_safety import UploadValidationError, validate_upload_relative_path
from packages.core.ingestion.paths import client_uploads_dir
from packages.core.ingestion.source_mapping import (
    SourceMappingValidationError,
    citation_status_for_upload,
    delete_mapping_entry,
    load_source_mapping,
    remove_mapping_entry_if_present,
    upsert_mapping_entry,
)
from packages.core.tenant.paths import client_config_dir, safe_client_id

router = APIRouter(
    prefix="/v1/admin/clients",
    tags=["admin-client-uploads"],
    dependencies=[Depends(require_admin_token)],
)


def _uploads_dir(client_id: str) -> Path:
    return client_uploads_dir(clients_root(), safe_client_id(client_id))


def _config_dir(client_id: str) -> Path:
    return client_config_dir(clients_root(), safe_client_id(client_id))


def _safe_upload_path(file_path: str) -> str:
    try:
        return validate_upload_relative_path(file_path)
    except UploadValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _build_citation_dto(client_id: str, rel_path: str, filename: str) -> UploadCitationDTO:
    config_dir = _config_dir(client_id)
    mapping = load_source_mapping(config_dir)
    whitelist = load_client_whitelist(clients_root(), client_id)
    resolved = citation_status_for_upload(
        rel_path=rel_path,
        filename=filename,
        mapping=mapping,
        whitelist=whitelist,
    )
    reingest = mapping_requires_reingest(clients_root(), client_id)
    return UploadCitationDTO(
        citation_url=resolved.configured_citation_url,
        title=resolved.configured_title or resolved.title,
        status=resolved.status,
        requires_reingest=reingest,
    )


@router.get("/{client_id}/uploads", response_model=UploadListDTO)
def list_uploads(
    client_id: str,
    admin: AdminContext = Depends(require_admin_token),
) -> UploadListDTO:
    _ = admin
    cid = safe_client_id(client_id)
    uploads = _uploads_dir(cid)
    files: list[UploadEntryDTO] = []
    if uploads.is_dir():
        for path in sorted(uploads.rglob("*")):
            if path.is_file():
                rel = path.relative_to(uploads).as_posix()
                files.append(
                    UploadEntryDTO(
                        path=rel,
                        size_bytes=path.stat().st_size,
                        citation=_build_citation_dto(cid, rel, path.name),
                    )
                )
    return UploadListDTO(files=files)


@router.post("/{client_id}/uploads", response_model=UploadResultDTO, status_code=status.HTTP_201_CREATED)
async def upload_file(
    client_id: str,
    file: UploadFile = File(...),
    admin: AdminContext = Depends(require_admin_token),
) -> UploadResultDTO:
    _ = admin
    filename = file.filename or ""
    try:
        rel = validate_upload_relative_path(filename)
    except UploadValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    uploads = _uploads_dir(client_id)
    uploads.mkdir(parents=True, exist_ok=True)
    dest = (uploads / rel).resolve()
    if not str(dest).startswith(str(uploads.resolve())):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path escapes uploads directory.")

    dest.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    dest.write_bytes(content)
    return UploadResultDTO(path=rel, size_bytes=len(content))


@router.put("/{client_id}/uploads/{file_path:path}/citation", response_model=UploadCitationDTO)
def put_upload_citation(
    client_id: str,
    file_path: str,
    payload: UploadCitationPutRequest,
    admin: AdminContext = Depends(require_admin_token),
) -> UploadCitationDTO:
    _ = admin
    cid = safe_client_id(client_id)
    rel = _safe_upload_path(file_path)
    uploads = _uploads_dir(cid)
    target = (uploads / rel).resolve()
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found.")

    whitelist = load_client_whitelist(clients_root(), cid)
    try:
        resolved = upsert_mapping_entry(
            _config_dir(cid),
            rel_path=rel,
            citation_url=payload.citation_url,
            title=payload.title,
            source_visibility=payload.source_visibility,
            whitelist=whitelist,
        )
    except (UploadValidationError, SourceMappingValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return UploadCitationDTO(
        citation_url=resolved.configured_citation_url,
        title=resolved.configured_title or resolved.title,
        status=resolved.status,
        requires_reingest=True,
    )


@router.delete("/{client_id}/uploads/{file_path:path}/citation", status_code=status.HTTP_204_NO_CONTENT)
def delete_upload_citation(
    client_id: str,
    file_path: str,
    admin: AdminContext = Depends(require_admin_token),
) -> Response:
    _ = admin
    cid = safe_client_id(client_id)
    rel = _safe_upload_path(file_path)
    try:
        delete_mapping_entry(_config_dir(cid), rel)
    except UploadValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{client_id}/uploads/{file_path:path}", status_code=status.HTTP_204_NO_CONTENT)
def delete_upload(
    client_id: str,
    file_path: str,
    admin: AdminContext = Depends(require_admin_token),
) -> Response:
    _ = admin
    cid = safe_client_id(client_id)
    rel = _safe_upload_path(file_path)

    uploads = _uploads_dir(cid)
    target = (uploads / rel).resolve()
    if not str(target).startswith(str(uploads.resolve())):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path escapes uploads directory.")
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found.")
    target.unlink()
    remove_mapping_entry_if_present(_config_dir(cid), rel)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
