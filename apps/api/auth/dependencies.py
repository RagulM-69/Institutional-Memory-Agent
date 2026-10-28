"""
FastAPI authentication and organization authorization dependencies.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator
from uuid import UUID

import asyncpg
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from apps.api.auth.jwt import AuthenticatedUser, verify_supabase_jwt
from apps.api.db.pool import transaction_context

logger = logging.getLogger(__name__)

# Security scheme that extracts the Bearer token without auto-erroring so we control 401 response
_bearer_scheme = HTTPBearer(auto_error=False)


class ActiveOrganization(BaseModel):
    """Represents the authorized active organization and user membership role."""
    org_id: UUID
    name: str
    slug: str
    role: str = Field(description="User role within organization: 'admin', 'team_lead', or 'member'")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthenticatedUser:
    """Dependency that extracts and cryptographically verifies the Supabase Auth JWT."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await verify_supabase_jwt(credentials.credentials)


async def get_organization_context(
    user: AuthenticatedUser = Depends(get_current_user),
    x_organization_id: str | None = Header(None, alias="X-Organization-Id"),
) -> tuple[AuthenticatedUser, ActiveOrganization]:
    """
    Resolve and authorize the active organization for the authenticated user.

    Rules:
    - If user has 0 memberships: 403 Forbidden.
    - If user belongs to multiple organizations and no X-Organization-Id header: 400 Bad Request.
    - If X-Organization-Id is provided: verify user is actually an active member of that org; if not: 403.
    - If user belongs to exactly 1 organization and no header provided: select it.
    """
    req_org_id: UUID | None = None
    if x_organization_id is not None:
        try:
            req_org_id = UUID(x_organization_id.strip())
        except (ValueError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Organization-Id header format: must be a valid UUID",
            ) from e

    # Query memberships for the authenticated user in a user-scoped transaction
    try:
        async with transaction_context(user_id=user.id) as conn:
            records = await conn.fetch("SELECT org_id, role, name, slug FROM public.get_user_memberships()")
    except Exception as e:
        logger.error("Failed to query user memberships for user %s: %s", user.id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while resolving organization memberships",
        ) from e

    if not records:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: user is not a member of any organization",
        )

    selected_record: asyncpg.Record | None = None

    if req_org_id is not None:
        for r in records:
            if str(r["org_id"]) == str(req_org_id):
                selected_record = r
                break
        if not selected_record:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: user is not an active member of the requested organization",
            )
    else:
        if len(records) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User belongs to multiple organizations; specify an active organization via X-Organization-Id header",
            )
        selected_record = records[0]

    role = selected_record["role"]
    if role not in ("admin", "team_lead", "member"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Invalid membership role: {role}",
        )

    active_org = ActiveOrganization(
        org_id=selected_record["org_id"],
        name=selected_record["name"],
        slug=selected_record["slug"],
        role=role,
    )

    return user, active_org


async def get_authorized_db(
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> AsyncIterator[asyncpg.Connection]:
    """
    Dependency yielding an active database connection within an explicit transaction
    where RLS context (`app.current_user_id` and `app.current_org_id`) is strictly bound.
    """
    user, org = context
    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        yield conn


async def require_admin(
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> tuple[AuthenticatedUser, ActiveOrganization]:
    """Dependency that restricts route access to organization administrators."""
    user, org = context
    if org.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: administrator privileges required",
        )
    return context


async def require_team_lead_or_admin(
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> tuple[AuthenticatedUser, ActiveOrganization]:
    """Dependency that restricts route access to team leads or organization administrators."""
    user, org = context
    if org.role not in ("admin", "team_lead"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: team lead or administrator privileges required",
        )
    return context

