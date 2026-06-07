from __future__ import annotations

import os

from packages.core.admin.roles import AdminContext, AdminRole
from packages.core.ports.admin_auth import AdminAuthError, AdminAuthProvider


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


class LocalTokenAdminAuthProvider(AdminAuthProvider):
    """MVP admin auth: x-admin-token → platform_admin, or explicit insecure local dev mode."""

    def resolve_admin(self, credential: str | None) -> AdminContext:
        profile = (os.getenv("STACK_PROFILE", "local") or "local").strip()
        expected = os.getenv("ADMIN_API_TOKEN", "").strip()
        allow_insecure = _truthy_env("ALLOW_INSECURE_ADMIN")

        if allow_insecure:
            if profile != "local":
                raise AdminAuthError(
                    "ALLOW_INSECURE_ADMIN is only permitted when STACK_PROFILE=local."
                )
            return AdminContext(role=AdminRole.PLATFORM_ADMIN, subject="insecure-dev-admin")

        if not expected:
            raise AdminAuthError(
                "Admin API token is not configured. Set ADMIN_API_TOKEN in the environment."
            )

        token = (credential or "").strip()
        if not token or token != expected:
            raise AdminAuthError("Invalid admin token.")
        return AdminContext(role=AdminRole.PLATFORM_ADMIN, subject="local-token-admin")
