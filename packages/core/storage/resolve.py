from __future__ import annotations

from pathlib import Path

from packages.core.storage.tenant_storage import TenantStorage


def resolve_storage(
    *,
    clients_root: Path | None = None,
    storage: TenantStorage | None = None,
) -> TenantStorage:
    if storage is not None:
        return storage
    if clients_root is None:
        raise ValueError("Either storage or clients_root is required.")
    return TenantStorage.local(clients_root)
