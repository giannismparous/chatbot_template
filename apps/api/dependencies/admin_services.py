from __future__ import annotations

from pathlib import Path

from apps.api.dependencies.stack import get_stack
from packages.core.admin.config_service import ConfigService
from packages.core.admin.registry import ClientRegistryService


def get_registry_service() -> ClientRegistryService:
    stack = get_stack()
    return ClientRegistryService(
        clients_root=stack.config_store.get_clients_root(),
        registry_store=stack.registry_store,
    )


def get_config_service() -> ConfigService:
    stack = get_stack()
    return ConfigService(
        clients_root=stack.config_store.get_clients_root(),
        tenant_storage=stack.tenant_storage,
        config_meta_store=stack.config_meta_store,
        registry_store=stack.registry_store,
    )


def get_job_runner():
    return get_stack().job_runner


def get_tenant_storage():
    return get_stack().tenant_storage


def clients_root() -> Path:
    return get_stack().config_store.get_clients_root()
