"""
API router for In-Platform Invitations.
Stores dual SHA-256 hashes at rest, enforces atomic single-use acceptance,
binds invitations to verified email identities, and protects against brute-force enumeration.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import string
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from apps.api.auth.dependencies import (
    ActiveOrganization,
    AuthenticatedUser,
    get_current_user,
    get_organization_context,
    require_admin,
    require_team_lead_or_admin,
)
from apps.api.config import settings
from apps.api.db.pool import transaction_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/invitations", tags=["invitations"])

_VALID_INVITE_ROLES = {"admin", "team_lead", "member"}

# ---------------------------------------------------------------------------
# In-Memory Sliding-Window Rate Limiter for Acceptance & Lookup
# Limits to max 5 failed/total lookup attempts per minute per user/IP
# ---------------------------------------------------------------------------
_RATE_LIMIT_WINDOW_SECONDS = 60
_MAX_ATTEMPTS_PER_WINDOW = 5
_attempt_history: Dict[str, List[float]] = defaultdict(list)


def _check_rate_limit(key: str) -> None:
    now = time.time()
    cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
    history = [t for t in _attempt_history[key] if t > cutoff]
    if len(history) >= _MAX_ATTEMPTS_PER_WINDOW:
        logger.warning("Invitation rate limit exceeded for key: %s", key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many invitation attempts. Please wait a minute before trying again.",
        )
    history.append(now)
    _attempt_history[key] = history


def _generate_invitation_secrets() -> Tuple[str, str, str, str]:
    """
    Returns (raw_token, raw_code, token_hash, code_hash).
    raw_token: 32 bytes URL-safe (high entropy >256 bits).
    raw_code: INV- + 12 alphanumeric characters (>60 bits entropy).
    """
    raw_token = secrets.token_urlsafe(32)
    charset = string.ascii_uppercase + string.digits
    raw_code = "INV-" + "".join(secrets.choice(charset) for _ in range(12))

    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    code_hash = hashlib.sha256(raw_code.encode("utf-8")).hexdigest()

    return raw_token, raw_code, token_hash, code_hash


def _mask_email(email: str) -> str:
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "***"
    else:
        masked_local = local[:2] + "***"
    return f"{masked_local}@{domain}"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CreateInvitationRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: str = Field(..., description="'admin', 'team_lead', or 'member'")


class InvitationCreatedResponse(BaseModel):
    id: UUID
    org_id: UUID
    invited_email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime
    # Returned strictly once to creating admin:
    raw_token: str
    raw_code: str
    token: str = ""
    code: str = ""
    invitation_link: str


class InvitationSummaryResponse(BaseModel):
    id: UUID
    org_id: UUID
    invited_email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime


class PendingInviteForUserResponse(BaseModel):
    id: UUID
    org_id: UUID
    org_name: str
    org_slug: str
    invited_email: str
    role: str
    expires_at: datetime
    created_at: datetime


class InvitationLookupRequest(BaseModel):
    code_or_token: str | None = None
    token: str | None = None
    code: str | None = None

    def get_value(self) -> str:
        val = self.code_or_token or self.token or self.code
        if not val or len(val.strip()) < 4:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must provide code_or_token, token, or code (min length 4).",
            )
        return val.strip()


class InvitationLookupResponse(BaseModel):
    id: UUID
    org_id: UUID
    org_name: str
    org_slug: str = ""
    masked_email: str
    email: str = ""
    role: str
    status: str
    expires_at: datetime
    can_accept: bool = True
    email_matches: bool = True
    is_expired: bool = False


class AcceptInvitationRequest(BaseModel):
    invitation_id: UUID | None = None
    code_or_token: str | None = None
    token: str | None = None
    code: str | None = None

    def get_value(self) -> str:
        if self.invitation_id:
            return str(self.invitation_id)
        val = self.code_or_token or self.token or self.code
        if not val or len(val.strip()) < 4:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must provide invitation_id, code_or_token, token, or code (min length 4).",
            )
        return val.strip()


class AcceptInvitationResponse(BaseModel):
    success: bool = True
    org_id: UUID
    org_name: str
    role: str
    status: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=InvitationCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    payload: CreateInvitationRequest,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(require_team_lead_or_admin),
) -> InvitationCreatedResponse:
    """
    Generate an in-platform invitation with single-use token and high-entropy code.
    Hashes both secrets before storing in the database.
    Raw secrets are returned strictly once in this response.
    """
    user, org = context
    target_email = payload.email.strip().lower()
    target_role = payload.role.strip().lower()

    if not _EMAIL_REGEX.match(target_email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email address format.",
        )

    if target_role not in _VALID_INVITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid invitation role '{target_role}'. Must be one of: {sorted(_VALID_INVITE_ROLES)}",
        )

    raw_token, raw_code, token_hash, code_hash = _generate_invitation_secrets()
    invitation_id = uuid4()

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        # 1. Check if user is already a member
        existing_member = await conn.fetchrow(
            """
            SELECT user_id
            FROM public.get_org_members($1)
            WHERE lower(email) = $2
            """,
            org.org_id,
            target_email,
        )
        if existing_member:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User with email '{target_email}' is already an active member of this organization.",
            )

        # 2. Check for active pending invitation
        existing_invite = await conn.fetchrow(
            """
            SELECT id
            FROM public.invitations
            WHERE org_id = $1 AND lower(invited_email) = $2 AND status = 'pending' AND expires_at > now()
            """,
            org.org_id,
            target_email,
        )
        if existing_invite:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A pending invitation already exists for '{target_email}'. Revoke or resend it.",
            )

        # 3. Insert invitation with dual hashes
        row = await conn.fetchrow(
            """
            INSERT INTO public.invitations (
                id, org_id, invited_email, role, token_hash, code_hash,
                status, created_by_user_id
            ) VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7)
            RETURNING id, org_id, invited_email, role, status, expires_at, created_at
            """,
            invitation_id,
            org.org_id,
            target_email,
            target_role,
            token_hash,
            code_hash,
            user.id,
        )

    base_url = settings.frontend_base_url.rstrip("/")
    invitation_link = f"{base_url}/invitations?code={raw_code}"

    return InvitationCreatedResponse(
        id=row["id"],
        org_id=row["org_id"],
        invited_email=row["invited_email"],
        role=row["role"],
        status=row["status"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        raw_token=raw_token,
        raw_code=raw_code,
        token=raw_token,
        code=raw_code,
        invitation_link=invitation_link,
    )


@router.get("", response_model=List[InvitationSummaryResponse])
async def list_invitations(
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(require_team_lead_or_admin),
) -> List[InvitationSummaryResponse]:
    """
    List all invitations for the active organization.
    Excludes all secret hashes and tokens.
    Requires administrator or team lead privileges.
    """
    user, org = context

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        rows = await conn.fetch(
            """
            SELECT id, org_id, invited_email, role, status, expires_at, created_at
            FROM public.invitations
            WHERE org_id = $1
            ORDER BY created_at DESC
            """,
            org.org_id,
        )
        return [
            InvitationSummaryResponse(
                id=r["id"],
                org_id=r["org_id"],
                invited_email=r["invited_email"],
                role=r["role"],
                status=r["status"],
                expires_at=r["expires_at"],
                created_at=r["created_at"],
            )
            for r in rows
        ]


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_or_revoke_invitation(
    invitation_id: UUID,
    permanent: bool = Query(default=False, description="Whether to permanently delete the invitation record."),
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(require_team_lead_or_admin),
) -> None:
    """
    Revoke or permanently delete an invitation.
    Requires administrator or team lead privileges.
    """
    user, org = context

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        if permanent:
            res = await conn.execute(
                """
                DELETE FROM public.invitations
                WHERE id = $1 AND org_id = $2
                """,
                invitation_id,
                org.org_id,
            )
        else:
            res = await conn.execute(
                """
                UPDATE public.invitations
                SET status = 'revoked', updated_at = now()
                WHERE id = $1 AND org_id = $2
                """,
                invitation_id,
                org.org_id,
            )
        if res in ("UPDATE 0", "DELETE 0"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation not found.",
            )


@router.post("/{invitation_id}/resend", response_model=InvitationCreatedResponse)
async def resend_invitation(
    invitation_id: UUID,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(require_team_lead_or_admin),
) -> InvitationCreatedResponse:
    """
    Revoke the previous invitation and issue fresh cryptographically secure credentials.
    Resets expiration to 7 days from now.
    """
    user, org = context

    raw_token, raw_code, token_hash, code_hash = _generate_invitation_secrets()

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        existing = await conn.fetchrow(
            "SELECT invited_email, role FROM public.invitations WHERE id = $1 AND org_id = $2",
            invitation_id,
            org.org_id,
        )
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation not found.",
            )

        # Revoke old
        await conn.execute(
            "UPDATE public.invitations SET status = 'revoked', updated_at = now() WHERE id = $1",
            invitation_id,
        )

        # Create new
        new_id = uuid4()
        row = await conn.fetchrow(
            """
            INSERT INTO public.invitations (
                id, org_id, invited_email, role, token_hash, code_hash,
                status, created_by_user_id
            ) VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7)
            RETURNING id, org_id, invited_email, role, status, expires_at, created_at
            """,
            new_id,
            org.org_id,
            existing["invited_email"],
            existing["role"],
            token_hash,
            code_hash,
            user.id,
        )

    base_url = settings.frontend_base_url.rstrip("/")
    invitation_link = f"{base_url}/invitations?code={raw_code}"

    return InvitationCreatedResponse(
        id=row["id"],
        org_id=row["org_id"],
        invited_email=row["invited_email"],
        role=row["role"],
        status=row["status"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        raw_token=raw_token,
        raw_code=raw_code,
        token=raw_token,
        code=raw_code,
        invitation_link=invitation_link,
    )


@router.get("/pending-for-me", response_model=List[PendingInviteForUserResponse])
async def list_pending_invitations_for_me(
    user: AuthenticatedUser = Depends(get_current_user),
) -> List[PendingInviteForUserResponse]:
    """
    Retrieve active pending invitations addressed to the authenticated user's email address.
    Invokes security-definer function get_my_pending_invitations.
    """
    async with transaction_context(user_id=user.id) as conn:
        rows = await conn.fetch("SELECT * FROM public.get_my_pending_invitations()")
        return [
            PendingInviteForUserResponse(
                id=r["id"],
                org_id=r["org_id"],
                org_name=r["org_name"],
                org_slug=r["org_slug"],
                invited_email=r["invited_email"],
                role=r["role"],
                expires_at=r["expires_at"],
                created_at=r["created_at"],
            )
            for r in rows
        ]


@router.post("/lookup", response_model=InvitationLookupResponse)
async def lookup_invitation(
    payload: InvitationLookupRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> InvitationLookupResponse:
    """
    Preview invitation details (organization name, role) prior to acceptance.
    Rate-limited to prevent brute-force code enumeration.
    """
    rate_key = f"{user.id}:{request.client.host if request.client else 'unknown'}"
    _check_rate_limit(rate_key)

    raw_input = payload.get_value()
    lookup_arg: str
    try:
        val_uuid = UUID(raw_input)
        lookup_arg = str(val_uuid)
    except (ValueError, AttributeError):
        lookup_arg = hashlib.sha256(raw_input.encode("utf-8")).hexdigest()

    async with transaction_context(user_id=user.id) as conn:
        row = await conn.fetchrow(
            "SELECT * FROM public.lookup_invitation($1)",
            lookup_arg,
        )

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation not found. Verify the code or link.",
            )

        if row["status"] != "pending":
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=f"This invitation is no longer active (status: {row['status']}).",
            )

        if row["expires_at"] <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="This invitation has expired.",
            )

        # Resolve user email reliably from token or database identity
        user_email = (user.email or "").strip().lower()
        if not user_email:
            user_db = await conn.fetchrow("SELECT email FROM auth.users WHERE id = $1", user.id)
            if user_db and user_db["email"]:
                user_email = user_db["email"].strip().lower()

        invited_email = (row["invited_email"] or "").strip().lower()
        email_matches = bool(user_email and user_email == invited_email)
        is_expired = row["expires_at"] <= datetime.now(timezone.utc)
        can_accept = email_matches and not is_expired and row["status"] == "pending"

        return InvitationLookupResponse(
            id=row["id"],
            org_id=row["org_id"],
            org_name=row["org_name"],
            org_slug=row["org_slug"] or "",
            masked_email=_mask_email(row["invited_email"]),
            email=row["invited_email"] if email_matches else _mask_email(row["invited_email"]),
            role=row["role"],
            status=row["status"],
            expires_at=row["expires_at"],
            can_accept=can_accept,
            email_matches=email_matches,
            is_expired=is_expired,
        )


@router.post("/accept", response_model=AcceptInvitationResponse)
async def accept_invitation(
    payload: AcceptInvitationRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AcceptInvitationResponse:
    """
    Accept an invitation using an atomic database transaction.
    Verifies email identity match, pending status, and unexpired validity.
    Atomically inserts membership without overwriting existing roles.
    """
    rate_key = f"{user.id}:{request.client.host if request.client else 'unknown'}"
    _check_rate_limit(rate_key)

    raw_input = payload.get_value()
    is_uuid = False
    try:
        val_uuid = UUID(raw_input)
        is_uuid = True
    except (ValueError, AttributeError):
        is_uuid = False

    if is_uuid:
        hash_arg = str(val_uuid)
        hash_type = "id"
    else:
        hash_arg = hashlib.sha256(raw_input.encode("utf-8")).hexdigest()
        hash_type = "code" if raw_input.upper().startswith("INV-") else "token"

    async with transaction_context(user_id=user.id) as conn:
        try:
            res = await conn.fetchrow(
                "SELECT * FROM public.accept_organization_invitation($1, $2)",
                hash_arg,
                hash_type,
            )
        except asyncpg.PostgresError as e:
            if e.sqlstate == "P0002":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Invitation not found. Please verify the code or link.",
                )
            elif e.sqlstate == "P0003":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This invitation is no longer pending or has already been accepted.",
                )
            elif e.sqlstate == "P0004":
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail="This invitation has expired.",
                )
            elif e.sqlstate == "P0005":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Email address mismatch: this invitation was issued to a different address.",
                )
            elif e.sqlstate == "P0007":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="You are already an active member of this organization.",
                )
            logger.error("Failed to accept invitation for user %s: %s", user.id, e)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to accept invitation.",
            )

        return AcceptInvitationResponse(
            success=True,
            org_id=res["org_id"],
            org_name=res["org_name"],
            role=res["role"],
            status="accepted",
        )


@router.post("/decline")
async def decline_invitation(
    payload: AcceptInvitationRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, str]:
    """
    Decline an invitation.
    """
    raw_input = payload.get_value()
    is_uuid = False
    try:
        val_uuid = UUID(raw_input)
        is_uuid = True
    except (ValueError, AttributeError):
        is_uuid = False

    if is_uuid:
        hash_arg = str(val_uuid)
        hash_type = "id"
    else:
        hash_arg = hashlib.sha256(raw_input.encode("utf-8")).hexdigest()
        hash_type = "code" if raw_input.upper().startswith("INV-") else "token"

    async with transaction_context(user_id=user.id) as conn:
        try:
            await conn.execute(
                "SELECT public.decline_organization_invitation($1, $2)",
                hash_arg,
                hash_type,
            )
        except asyncpg.PostgresError as e:
            if e.sqlstate == "P0002":
                raise HTTPException(status_code=404, detail="Invitation not found.")
            elif e.sqlstate == "P0005":
                raise HTTPException(status_code=403, detail="Email mismatch.")
            raise HTTPException(status_code=400, detail="Unable to decline invitation.")

    return {"status": "declined"}
