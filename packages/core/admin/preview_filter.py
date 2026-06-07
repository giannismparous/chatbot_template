from __future__ import annotations

from packages.core.admin.roles import AdminContext, AdminRole


def filter_preview_summary(admin: AdminContext, summary: dict) -> dict:
    """Scaffold for future client_admin preview — Phase 12 requires platform_admin."""
    if admin.role == AdminRole.PLATFORM_ADMIN:
        return summary
    return {
        "retrieved_count": summary.get("retrieved_count", 0),
        "no_context": summary.get("no_context", False),
    }
