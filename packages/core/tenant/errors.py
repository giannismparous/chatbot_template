from __future__ import annotations


class TenantAuthError(Exception):
    """Base error for widget / tenant authentication."""


class WidgetKeyNotFoundError(TenantAuthError):
    pass


class OriginNotAllowedError(TenantAuthError):
    pass
