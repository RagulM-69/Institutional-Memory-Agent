"""
Authentication and authorization module.
"""

from apps.api.auth.dependencies import (
    ActiveOrganization,
    get_authorized_db,
    get_current_user,
    get_organization_context,
    require_admin,
)
from apps.api.auth.jwt import AuthenticatedUser, verify_supabase_jwt

__all__ = [
    "ActiveOrganization",
    "AuthenticatedUser",
    "get_authorized_db",
    "get_current_user",
    "get_organization_context",
    "require_admin",
    "verify_supabase_jwt",
]

