from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from apps.api.dependencies.admin_services import clients_root
from apps.api.dependencies.auth import require_admin_token
from apps.api.schemas_admin import (
    WebSourceCreateRequest,
    WebSourceDTO,
    WebSourcesListDTO,
)
from packages.core.admin.roles import AdminContext
from packages.core.config.loader import TenantConfigLoader
from packages.core.stack.factory import project_root
from packages.core.tenant.paths import client_config_dir, safe_client_id
from packages.core.web_sources.config import add_web_source, load_web_sources, remove_web_source
from packages.core.web_sources.service import delete_web_source_cache, list_web_sources_with_status
from packages.core.web_sources.validation import WebSourceValidationError, normalize_page_url, validate_source_id

router = APIRouter(
    prefix="/v1/admin/clients",
    tags=["admin-client-web-sources"],
    dependencies=[Depends(require_admin_token)],
)


def _loader() -> TenantConfigLoader:
    root = project_root()
    return TenantConfigLoader(
        clients_root=clients_root(),
        domain_packs_root=root / "packages" / "domain_packs",
    )


@router.get("/{client_id}/web-sources", response_model=WebSourcesListDTO)
def get_web_sources(
    client_id: str,
    admin: AdminContext = Depends(require_admin_token),
) -> WebSourcesListDTO:
    _ = admin
    cid = safe_client_id(client_id)
    loader = _loader()
    config = load_web_sources(client_config_dir(clients_root(), cid))
    rows = list_web_sources_with_status(clients_root=clients_root(), client_id=cid, config_loader=loader)
    return WebSourcesListDTO(
        defaults={
            "max_depth": config.defaults.max_depth,
            "max_pages": config.defaults.max_pages,
            "crawl_delay_ms": config.defaults.crawl_delay_ms,
            "respect_robots_txt": config.defaults.respect_robots_txt,
            "render_mode": config.defaults.render_mode,
            "wait_until": config.defaults.wait_until,
            "wait_selector": config.defaults.wait_selector,
        },
        sources=[WebSourceDTO(**row) for row in rows],
    )


@router.post("/{client_id}/web-sources", response_model=WebSourceDTO, status_code=status.HTTP_201_CREATED)
def create_web_source(
    client_id: str,
    payload: WebSourceCreateRequest,
    admin: AdminContext = Depends(require_admin_token),
) -> WebSourceDTO:
    _ = admin
    cid = safe_client_id(client_id)
    loader = _loader()
    merged = loader.load(cid)
    config_dir = client_config_dir(clients_root(), cid)
    try:
        add_web_source(
            config_dir,
            url=payload.url,
            title=payload.title,
            enabled=payload.enabled,
            max_depth=payload.max_depth,
            max_pages=payload.max_pages,
            source_id=payload.id,
            whitelist=merged.source_whitelist or {},
            crawl_settings=merged.ingestion,
            render_mode=payload.render_mode,
            wait_until=payload.wait_until,
            wait_selector=payload.wait_selector,
        )
    except WebSourceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    rows = list_web_sources_with_status(clients_root=clients_root(), client_id=cid, config_loader=loader)
    normalized = normalize_page_url(payload.url)
    created = next((row for row in rows if row["url"] == normalized), None)
    if created is None and payload.id:
        created = next((row for row in rows if row["id"] == payload.id), None)
    if created is None:
        created = rows[-1] if rows else None
    if created is None:
        raise HTTPException(status_code=500, detail="Failed to load created web source.")
    return WebSourceDTO(**created)


@router.delete("/{client_id}/web-sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_web_source(
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
        remove_web_source(config_dir, sid)
    except WebSourceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    delete_web_source_cache(clients_root(), cid, sid)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
