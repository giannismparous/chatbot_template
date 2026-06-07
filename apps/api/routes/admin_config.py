from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from apps.api.dependencies import container
from apps.api.dependencies.auth import require_admin_token
from packages.config.loaders import load_yaml, save_yaml

# DEPRECATED (Phase 11): legacy global admin config routes.
# Prefer per-client lifecycle API under /v1/admin/clients/{id}/...
router = APIRouter(
    prefix="/v1/admin",
    tags=["admin-legacy"],
    dependencies=[Depends(require_admin_token)],
)


class GenericConfigPayload(BaseModel):
    data: Dict[str, Any]


@router.get("/prompt-policy", deprecated=True)
def get_prompt_policy() -> dict:
    return load_yaml(container.PROMPT_POLICY_PATH)


@router.put("/prompt-policy", deprecated=True)
def put_prompt_policy(payload: GenericConfigPayload) -> dict:
    save_yaml(container.PROMPT_POLICY_PATH, payload.data)
    container.reload_runtime()
    return {"status": "ok"}


@router.get("/themes", deprecated=True)
def get_themes() -> dict:
    return load_yaml(container.THEME_PATH)


@router.put("/themes", deprecated=True)
def put_themes(payload: GenericConfigPayload) -> dict:
    save_yaml(container.THEME_PATH, payload.data)
    container.reload_runtime()
    return {"status": "ok"}


@router.get("/clients", deprecated=True)
def get_clients() -> dict:
    return load_yaml(container.CLIENTS_PATH)


@router.put("/clients", deprecated=True)
def put_clients(payload: GenericConfigPayload) -> dict:
    save_yaml(container.CLIENTS_PATH, payload.data)
    container.reload_runtime()
    return {"status": "ok"}


@router.get("/sources/drive")
def get_drive_sources() -> dict:
    return load_yaml(str(container.ROOT / "packages" / "config" / "defaults" / "drive_sources.yaml"))


@router.put("/sources/drive")
def put_drive_sources(payload: GenericConfigPayload) -> dict:
    path = str(container.ROOT / "packages" / "config" / "defaults" / "drive_sources.yaml")
    save_yaml(path, payload.data)
    return {"status": "ok"}


@router.get("/sources/api")
def get_api_sources() -> dict:
    return load_yaml(container.API_SOURCES_PATH)


@router.put("/sources/api")
def put_api_sources(payload: GenericConfigPayload) -> dict:
    save_yaml(container.API_SOURCES_PATH, payload.data)
    container.reload_runtime()
    return {"status": "ok"}
