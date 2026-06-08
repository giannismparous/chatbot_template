from __future__ import annotations

import os
from pathlib import Path

from packages.core.storage.tenant_storage import TenantStorage


def tenant_storage_for_worker(clients_root: Path) -> TenantStorage:
    """Resolve tenant storage for worker jobs (GCS on firebase, local filesystem otherwise)."""
    if os.getenv("STACK_PROFILE", "local").strip() == "firebase":
        from packages.core.stack.factory import build_stack

        return build_stack().tenant_storage
    return TenantStorage.local(clients_root)
