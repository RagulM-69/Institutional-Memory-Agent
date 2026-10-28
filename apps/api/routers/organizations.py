"""
API router for Organization Onboarding and Team Member Management.
Enforces organization boundaries, tenant isolation, and last-admin protection.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import List, Optional
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from apps.api.auth.dependencies import (
    ActiveOrganization,
    AuthenticatedUser,
    get_current_user,
    get_organization_context,
    require_admin,
)
from apps.api.db.pool import transaction_context

logger = logging.getLogger(__name__)

router = APIRouter(tags=["organizations"])

_SLUG_REGEX = re.compile(r"^[a-z0-9-]+$")
_VALID_ROLES = {"admin", "team_lead", "member"}


class CreateOrganizationRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=3, max_length=48)


class OrganizationMembershipSummary(BaseModel):
    org_id: UUID
    name: str
    slug: str
    role: str


class TeamMemberResponse(BaseModel):
    user_id: UUID
    email: Optional[str] = None
    role: str
    joined_at: datetime


class UpdateMemberRoleRequest(BaseModel):
    role: str = Field(..., description="Target role: 'admin', 'team_lead', or 'member'")


# ---------------------------------------------------------------------------
# Organization Onboarding & Listing
# ---------------------------------------------------------------------------

@router.get("/api/me/organizations", response_model=List[OrganizationMembershipSummary])
async def list_my_organizations(
    user: AuthenticatedUser = Depends(get_current_user),
) -> List[OrganizationMembershipSummary]:
    """
    List all organizations the authenticated user belongs to.
    """
    async with transaction_context(user_id=user.id) as conn:
        records = await conn.fetch("SELECT org_id, role, name, slug FROM public.get_user_memberships()")
        return [
            OrganizationMembershipSummary(
                org_id=r["org_id"],
                name=r["name"],
                slug=r["slug"],
                role=r["role"],
            )
            for r in records
        ]


@router.post("/api/organizations", response_model=OrganizationMembershipSummary, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: CreateOrganizationRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> OrganizationMembershipSummary:
    """
    Create a new organization and establish the caller as its initial administrator.
    Atomically executed via security-definer function create_organization_with_owner.
    """
    clean_name = payload.name.strip()
    clean_slug = payload.slug.strip().lower()

    if not _SLUG_REGEX.match(clean_slug):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization slug must contain only lowercase letters, numbers, and hyphens.",
        )

    async with transaction_context(user_id=user.id) as conn:
        # Check if slug is already taken
        existing = await conn.fetchrow("SELECT id FROM public.organizations WHERE slug = $1", clean_slug)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Organization slug '{clean_slug}' is already in use. Please choose another.",
            )

        try:
            new_org_id = await conn.fetchval(
                "SELECT public.create_organization_with_owner($1, $2)",
                clean_name,
                clean_slug,
            )
        except asyncpg.PostgresError as e:
            logger.error("Failed to create organization for user %s: %s", user.id, e)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        return OrganizationMembershipSummary(
            org_id=new_org_id,
            name=clean_name,
            slug=clean_slug,
            role="admin",
        )


# ---------------------------------------------------------------------------
# Team Members Management
# ---------------------------------------------------------------------------

@router.get("/api/team/members", response_model=List[TeamMemberResponse])
async def list_team_members(
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> List[TeamMemberResponse]:
    """
    List organization members.
    Enforces directory privacy: Admins and Team Leads see all members with emails.
    Regular members see only their own record to prevent unauthorized directory scraping.
    """
    user, org = context

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        rows = await conn.fetch(
            "SELECT user_id, email, role, created_at FROM public.get_org_members($1)",
            org.org_id,
        )
        return [
            TeamMemberResponse(
                user_id=r["user_id"],
                email=r["email"],
                role=r["role"],
                joined_at=r["created_at"],
            )
            for r in rows
        ]


@router.patch("/api/team/members/{target_user_id}", response_model=TeamMemberResponse)
async def update_member_role(
    target_user_id: UUID,
    payload: UpdateMemberRoleRequest,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(require_admin),
) -> TeamMemberResponse:
    """
    Update a member's role within the organization.
    Requires administrator privileges.
    Guaranteed by database trigger against demoting the sole administrator.
    """
    user, org = context
    target_role = payload.role.strip().lower()

    if target_role not in _VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{target_role}'. Must be one of: {sorted(_VALID_ROLES)}",
        )

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        existing = await conn.fetchrow(
            """
            SELECT user_id, role, email, created_at
            FROM public.get_org_members($1)
            WHERE user_id = $2
            """,
            org.org_id,
            target_user_id,
        )
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found in this organization.",
            )

        try:
            await conn.execute(
                """
                UPDATE public.memberships
                SET role = $1
                WHERE org_id = $2 AND user_id = $3
                """,
                target_role,
                org.org_id,
                target_user_id,
            )
        except asyncpg.PostgresError as e:
            if e.sqlstate == "P0001":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot demote the last administrator of the organization.",
                )
            logger.error("Failed to update role for user %s: %s", target_user_id, e)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Database rejected role update.",
            )

        return TeamMemberResponse(
            user_id=target_user_id,
            email=existing["email"],
            role=target_role,
            joined_at=existing["created_at"],
        )


@router.delete("/api/team/members/{target_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    target_user_id: UUID,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(require_admin),
) -> None:
    """
    Remove a member from the organization, immediately revoking their access.
    Requires administrator privileges.
    Guaranteed by database trigger against removing the sole administrator.
    """
    user, org = context

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM public.memberships WHERE org_id = $1 AND user_id = $2",
            org.org_id,
            target_user_id,
        )
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found in this organization.",
            )

        try:
            await conn.execute(
                "DELETE FROM public.memberships WHERE org_id = $1 AND user_id = $2",
                org.org_id,
                target_user_id,
            )
        except asyncpg.PostgresError as e:
            if e.sqlstate == "P0001":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot remove the last administrator of the organization.",
                )
            logger.error("Failed to delete member %s: %s", target_user_id, e)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Database rejected member deletion.",
            )

