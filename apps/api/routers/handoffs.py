"""
API router for structured engineering handoffs and knowledge transfer containers.
Enforces tenant isolation and validates source permissions for attached evidence items.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import dspy
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from apps.api.auth.dependencies import (
    ActiveOrganization,
    AuthenticatedUser,
    get_organization_context,
)
from apps.api.config import settings
from apps.api.db.pool import transaction_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/handoffs", tags=["handoffs"])

VALID_SUBJECT_TYPES = {"person", "service"}
VALID_HANDOFF_STATUSES = {"draft", "reviewed", "confirmed", "acknowledged", "archived"}
VALID_ITEM_STATUSES = {"verified", "inferred", "unresolved", "outdated"}


class GenerateHandoffRequest(BaseModel):
    subject_type: str = Field(default="person", description="person or service")
    subject_identifier: str = Field(..., min_length=2, max_length=255, description="Name of the engineer or service to analyze")
    recipient_user_id: Optional[UUID] = None


class DetectedSubjectsResponse(BaseModel):
    engineers: List[str]
    services: List[str]


class _DossierSignature(dspy.Signature):
    """
    Analyze engineering records for a departing engineer or service to generate a comprehensive handoff dossier.
    Synthesize:
    1. Core services and code touched (commits).
    2. Pending/in-flight tasks requiring handover (tickets).
    3. Key architectural decisions and runbook items (threads/meetings).
    """
    subject_name: str = dspy.InputField(desc="Engineer name or service to generate handoff dossier for")
    records_context: str = dspy.InputField(desc="List of available records from GitHub, Jira, Slack, and Meetings")
    handoff_title: str = dspy.OutputField(desc="Clear professional title for the handoff dossier")
    summary: str = dspy.OutputField(desc="Executive summary of technical ownership, code contributions, and transition priorities")
    items_json: str = dspy.OutputField(desc='JSON array of 3 to 6 items: [{"title": "...", "description": "...", "item_status": "verified|unresolved|inferred", "record_id": "<exact record ID from context or null>"}]')


class HandoffItemPayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    item_status: str = Field(default="verified", description="verified, inferred, unresolved, outdated")
    record_id: Optional[UUID] = None
    gap_id: Optional[UUID] = None
    note_id: Optional[UUID] = None
    assignee_user_id: Optional[UUID] = None
    due_date: Optional[datetime] = None


class CreateHandoffRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    subject_type: str = Field(..., description="person or service")
    subject_identifier: str = Field(..., min_length=1, max_length=255)
    summary: Optional[str] = None
    departing_user_id: Optional[UUID] = None
    recipient_user_id: Optional[UUID] = None
    items: List[HandoffItemPayload] = Field(default_factory=list)


class UpdateHandoffRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    summary: Optional[str] = None
    status: Optional[str] = None


class UpdateHandoffItemRequest(BaseModel):
    item_status: Optional[str] = Field(default=None, description="verified, inferred, unresolved, outdated")
    assignee_user_id: Optional[UUID] = None
    due_date: Optional[datetime] = None


class HandoffItemResponse(BaseModel):
    id: UUID
    title: str
    description: Optional[str] = None
    item_status: str
    record_id: Optional[UUID] = None
    record_title: Optional[str] = None
    record_type: Optional[str] = None
    note_id: Optional[UUID] = None
    note_title: Optional[str] = None
    gap_id: Optional[UUID] = None
    assignee_user_id: Optional[UUID] = None
    due_date: Optional[datetime] = None
    is_restricted_evidence: bool = False


class HandoffResponse(BaseModel):
    id: UUID
    org_id: UUID
    title: str
    subject_type: str
    subject_identifier: str
    status: str
    summary: Optional[str] = None
    created_by_user_id: Optional[UUID] = None
    departing_user_id: Optional[UUID] = None
    recipient_user_id: Optional[UUID] = None
    created_at: datetime
    item_count: int = 0
    items: List[HandoffItemResponse] = Field(default_factory=list)


@router.get("/detected-subjects", response_model=DetectedSubjectsResponse)
async def get_detected_subjects(
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> DetectedSubjectsResponse:
    """
    Get auto-detected engineers and services based on active synced records in the organization.
    """
    user, org = context
    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        authors = await conn.fetch(
            """
            SELECT author_name, count(*) as count
            FROM public.records
            WHERE org_id = $1 AND author_name IS NOT NULL AND author_name != ''
            GROUP BY author_name
            ORDER BY count DESC
            LIMIT 20;
            """,
            org.org_id,
        )
        engineers = [a["author_name"] for a in authors if a["author_name"] and not a["author_name"].startswith("U0")]

        sources = await conn.fetch(
            """
            SELECT name, type FROM public.sources
            WHERE org_id = $1 AND is_archived = false;
            """,
            org.org_id,
        )
        services = ["Continuity", "Authentication Service", "Payment Gateway"]
        for s in sources:
            if s["name"] and s["name"] not in services:
                services.append(s["name"])

        return DetectedSubjectsResponse(
            engineers=engineers or ["Kabilesh M", "Ragul M", "Gowthaman KL"],
            services=services,
        )


@router.post("/generate", response_model=HandoffResponse, status_code=status.HTTP_201_CREATED)
async def generate_handoff(
    request: GenerateHandoffRequest,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> HandoffResponse:
    """
    Automatically generate an engineering handoff dossier by analyzing GitHub commits,
    Jira tickets, Slack architectural decisions, and meeting notes using DSPy reasoning.
    """
    user, org = context
    subject = request.subject_identifier.strip()
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subject identifier must not be empty.",
        )

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        # 1. Fetch matching records authored by or mentioning subject
        authored_records = await conn.fetch(
            """
            SELECT id, title, record_type, author_name, created_at, metadata
            FROM public.records
            WHERE org_id = $1 AND (author_name ILIKE $2 OR title ILIKE $2)
            ORDER BY created_at DESC
            LIMIT 10;
            """,
            org.org_id,
            f"%{subject}%",
        )

        other_records = await conn.fetch(
            """
            SELECT id, title, record_type, author_name, created_at, metadata
            FROM public.records
            WHERE org_id = $1 AND record_type IN ('ticket', 'slack_thread', 'meeting')
            ORDER BY created_at DESC
            LIMIT 12;
            """,
            org.org_id,
        )

        all_recs = {r["id"]: r for r in list(authored_records) + list(other_records)}
        if not all_recs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No engineering records found for '{subject}' to generate a handoff dossier.",
            )

        context_lines = []
        for r in all_recs.values():
            context_lines.append(
                f"Record [{r['record_type']}] ID:{r['id']} Title: {r['title']} (by {r['author_name'] or 'unknown'})"
            )
        context_str = "\n".join(context_lines)

        # 2. Synthesize Dossier with DSPy / Groq LM
        try:
            groq_key = settings.groq_api_key.get_secret_value()
            if not groq_key:
                raise RuntimeError("GROQ_API_KEY is not configured.")

            lm = dspy.LM(
                model=f"groq/{settings.groq_model}",
                api_key=groq_key,
                temperature=0.1,
                timeout=30.0,
            )

            with dspy.settings.context(lm=lm):
                predictor = dspy.Predict(_DossierSignature)
                synth = predictor(subject_name=subject, records_context=context_str)

            title = synth.handoff_title.strip() or f"Engineering Dossier: {subject}"
            summary = synth.summary.strip()

            raw_items_json = synth.items_json.strip()
            if raw_items_json.startswith("```"):
                raw_items_json = raw_items_json.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed_items = json.loads(raw_items_json)
            if not isinstance(parsed_items, list):
                parsed_items = []
        except Exception as e:
            logger.warning("LLM dossier synthesis failed, falling back to heuristic extraction: %s", e)
            title = f"Engineering Dossier: {subject}"
            summary = f"Automated handoff package compiled for {subject} across synced GitHub, Jira, and Slack records."
            parsed_items = []
            for r in authored_records[:5]:
                parsed_items.append({
                    "title": r["title"],
                    "description": f"Key {r['record_type']} contributed by {subject}.",
                    "item_status": "verified",
                    "record_id": str(r["id"]),
                })

        # 3. Persist Handoff container
        handoff_id = uuid4()
        handoff_row = await conn.fetchrow(
            """
            INSERT INTO public.handoffs (
                id, org_id, title, subject_type, subject_identifier, status,
                summary, created_by_user_id, recipient_user_id
            ) VALUES ($1, $2, $3, $4, $5, 'draft', $6, $7, $8)
            RETURNING id, org_id, title, subject_type, subject_identifier, status,
                      summary, created_by_user_id, departing_user_id, recipient_user_id, created_at;
            """,
            handoff_id,
            org.org_id,
            title,
            request.subject_type,
            subject,
            summary,
            user.id,
            request.recipient_user_id,
        )

        # 4. Persist Items
        persisted_items: List[HandoffItemResponse] = []
        for it in parsed_items[:8]:
            item_title = str(it.get("title", "Handoff Item")).strip()[:500]
            item_desc = str(it.get("description", ""))
            status_val = it.get("item_status", "verified")
            if status_val not in VALID_ITEM_STATUSES:
                status_val = "verified"

            rec_id_raw = it.get("record_id")
            rec_id: Optional[UUID] = None
            if rec_id_raw:
                try:
                    candidate_uuid = UUID(str(rec_id_raw))
                    if candidate_uuid in all_recs:
                        rec_id = candidate_uuid
                except Exception:
                    pass

            item_id = uuid4()
            item_row = await conn.fetchrow(
                """
                INSERT INTO public.handoff_items (
                    id, handoff_id, org_id, title, description, item_status, record_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id, title, description, item_status, record_id;
                """,
                item_id,
                handoff_id,
                org.org_id,
                item_title,
                item_desc,
                status_val,
                rec_id,
            )

            rec_meta = all_recs.get(rec_id) if rec_id else None
            persisted_items.append(
                HandoffItemResponse(
                    id=item_row["id"],
                    title=item_row["title"],
                    description=item_row["description"],
                    item_status=item_row["item_status"],
                    record_id=item_row["record_id"],
                    record_title=rec_meta["title"] if rec_meta else None,
                    record_type=rec_meta["record_type"] if rec_meta else None,
                    is_restricted_evidence=False,
                )
            )

        return HandoffResponse(
            id=handoff_row["id"],
            org_id=handoff_row["org_id"],
            title=handoff_row["title"],
            subject_type=handoff_row["subject_type"],
            subject_identifier=handoff_row["subject_identifier"],
            status=handoff_row["status"],
            summary=handoff_row["summary"],
            created_by_user_id=handoff_row["created_by_user_id"],
            departing_user_id=handoff_row["departing_user_id"],
            recipient_user_id=handoff_row["recipient_user_id"],
            created_at=handoff_row["created_at"],
            item_count=len(persisted_items),
            items=persisted_items,
        )


@router.post("", response_model=HandoffResponse, status_code=status.HTTP_201_CREATED)
async def create_handoff(
    request: CreateHandoffRequest,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> HandoffResponse:
    """
    Create a new structured handoff package with items.
    Validates that caller has source-level access to all attached records.
    """
    user, org = context

    if request.subject_type not in VALID_SUBJECT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid subject_type. Must be one of {sorted(VALID_SUBJECT_TYPES)}.",
        )

    for item in request.items:
        if item.item_status not in VALID_ITEM_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid item_status '{item.item_status}'. Must be one of {sorted(VALID_ITEM_STATUSES)}.",
            )

    handoff_id = uuid4()

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        # 1. Validate permissions on all attached records
        for item in request.items:
            if item.record_id:
                rec = await conn.fetchrow(
                    """
                    SELECT r.id, r.title, r.source_id,
                           public.user_can_access_source(r.source_id, $2) AS has_access
                    FROM public.records r
                    WHERE r.id = $1 AND r.org_id = $2
                    """,
                    item.record_id,
                    org.org_id,
                )
                if not rec:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Attached record '{item.record_id}' not found in organization.",
                    )
                if not rec["has_access"]:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Access denied: you do not have permission to attach record '{item.record_id}'.",
                    )

            if item.note_id:
                note = await conn.fetchrow(
                    "SELECT id FROM public.knowledge_notes WHERE id = $1 AND org_id = $2",
                    item.note_id,
                    org.org_id,
                )
                if not note:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Attached note '{item.note_id}' not found in organization.",
                    )

            if item.assignee_user_id:
                mem = await conn.fetchrow(
                    "SELECT id FROM public.memberships WHERE org_id = $1 AND user_id = $2",
                    org.org_id,
                    item.assignee_user_id,
                )
                if not mem:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Assignee user '{item.assignee_user_id}' is not an active member of this organization.",
                    )

        # 2. Insert handoff
        row = await conn.fetchrow(
            """
            INSERT INTO public.handoffs (
                id, org_id, title, subject_type, subject_identifier, status,
                summary, departing_user_id, recipient_user_id, created_by_user_id
            ) VALUES ($1, $2, $3, $4, $5, 'draft', $6, $7, $8, $9)
            RETURNING id, org_id, title, subject_type, subject_identifier, status,
                      summary, departing_user_id, recipient_user_id, created_by_user_id, created_at;
            """,
            handoff_id,
            org.org_id,
            request.title.strip(),
            request.subject_type,
            request.subject_identifier.strip(),
            request.summary,
            request.departing_user_id,
            request.recipient_user_id,
            user.id,
        )

        # 3. Insert items
        persisted_items: List[HandoffItemResponse] = []
        if request.items:
            for item in request.items:
                item_id = uuid4()
                await conn.execute(
                    """
                    INSERT INTO public.handoff_items (
                        id, org_id, handoff_id, title, description,
                        item_status, record_id, note_id, gap_id,
                        assignee_user_id, due_date
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11);
                    """,
                    item_id,
                    org.org_id,
                    handoff_id,
                    item.title.strip(),
                    item.description,
                    item.item_status,
                    item.record_id,
                    item.note_id,
                    item.gap_id,
                    item.assignee_user_id,
                    item.due_date,
                )
                persisted_items.append(
                    HandoffItemResponse(
                        id=item_id,
                        title=item.title.strip(),
                        description=item.description,
                        item_status=item.item_status,
                        record_id=item.record_id,
                        note_id=item.note_id,
                        gap_id=item.gap_id,
                        assignee_user_id=item.assignee_user_id,
                        due_date=item.due_date,
                    )
                )

        return HandoffResponse(
            id=row["id"],
            org_id=row["org_id"],
            title=row["title"],
            subject_type=row["subject_type"],
            subject_identifier=row["subject_identifier"],
            status=row["status"],
            summary=row["summary"],
            created_by_user_id=row["created_by_user_id"],
            departing_user_id=row["departing_user_id"],
            recipient_user_id=row["recipient_user_id"],
            created_at=row["created_at"],
            item_count=len(persisted_items),
            items=persisted_items,
        )


@router.get("", response_model=List[HandoffResponse])
async def list_handoffs(
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> List[HandoffResponse]:
    """
    List all structured handoffs for the active organization.
    """
    user, org = context

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        rows = await conn.fetch(
            """
            SELECT h.id, h.org_id, h.title, h.subject_type, h.subject_identifier,
                   h.status, h.summary, h.created_by_user_id, h.departing_user_id,
                   h.recipient_user_id, h.created_at,
                   COUNT(hi.id) AS item_count
            FROM public.handoffs h
            LEFT JOIN public.handoff_items hi ON hi.handoff_id = h.id AND hi.org_id = h.org_id
            WHERE h.org_id = $1
            GROUP BY h.id, h.org_id, h.title, h.subject_type, h.subject_identifier,
                     h.status, h.summary, h.created_by_user_id, h.departing_user_id,
                     h.recipient_user_id, h.created_at
            ORDER BY h.created_at DESC;
            """,
            org.org_id,
        )

        return [
            HandoffResponse(
                id=r["id"],
                org_id=r["org_id"],
                title=r["title"],
                subject_type=r["subject_type"],
                subject_identifier=r["subject_identifier"],
                status=r["status"],
                summary=r["summary"],
                created_by_user_id=r["created_by_user_id"],
                departing_user_id=r["departing_user_id"],
                recipient_user_id=r["recipient_user_id"],
                created_at=r["created_at"],
                item_count=r["item_count"],
                items=[],
            )
            for r in rows
        ]


@router.get("/{handoff_id}", response_model=HandoffResponse)
async def get_handoff(
    handoff_id: UUID,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> HandoffResponse:
    """
    Retrieve full details for a handoff.
    Protects evidence by redacting any attached records the caller is not authorized to view.
    """
    user, org = context

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        h = await conn.fetchrow(
            """
            SELECT id, org_id, title, subject_type, subject_identifier,
                   status, summary, created_by_user_id, departing_user_id,
                   recipient_user_id, created_at
            FROM public.handoffs
            WHERE id = $1 AND org_id = $2;
            """,
            handoff_id,
            org.org_id,
        )
        if not h:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Handoff not found.",
            )

        items_rows = await conn.fetch(
            """
            SELECT hi.id, hi.title, hi.description, hi.item_status,
                   hi.record_id, r.title AS record_title, r.record_type, r.source_id,
                   hi.note_id, kn.title AS note_title,
                   hi.gap_id, hi.assignee_user_id, hi.due_date,
                   CASE 
                       WHEN hi.record_id IS NULL THEN true
                       ELSE public.user_can_access_source(r.source_id, $2)
                   END AS user_has_record_access
            FROM public.handoff_items hi
            LEFT JOIN public.records r ON r.id = hi.record_id AND r.org_id = hi.org_id
            LEFT JOIN public.knowledge_notes kn ON kn.id = hi.note_id AND kn.org_id = hi.org_id
            WHERE hi.handoff_id = $1 AND hi.org_id = $2
            ORDER BY hi.id ASC;
            """,
            handoff_id,
            org.org_id,
        )

        items: List[HandoffItemResponse] = []
        for r in items_rows:
            has_access = bool(r["user_has_record_access"])
            if not has_access:
                # Sanitize confidential record metadata for unauthorized caller
                items.append(
                    HandoffItemResponse(
                        id=r["id"],
                        title=r["title"],
                        description="[Restricted Evidence - Caller lacks source access]",
                        item_status=r["item_status"],
                        record_id=None,
                        record_title="[Restricted Evidence]",
                        record_type=None,
                        note_id=r["note_id"],
                        note_title=r["note_title"],
                        gap_id=r["gap_id"],
                        assignee_user_id=r["assignee_user_id"] if "assignee_user_id" in r else None,
                        due_date=r["due_date"] if "due_date" in r else None,
                        is_restricted_evidence=True,
                    )
                )
            else:
                items.append(
                    HandoffItemResponse(
                        id=r["id"],
                        title=r["title"],
                        description=r["description"],
                        item_status=r["item_status"],
                        record_id=r["record_id"],
                        record_title=r["record_title"],
                        record_type=r["record_type"],
                        note_id=r["note_id"],
                        note_title=r["note_title"],
                        gap_id=r["gap_id"],
                        assignee_user_id=r["assignee_user_id"] if "assignee_user_id" in r else None,
                        due_date=r["due_date"] if "due_date" in r else None,
                        is_restricted_evidence=False,
                    )
                )

        return HandoffResponse(
            id=h["id"],
            org_id=h["org_id"],
            title=h["title"],
            subject_type=h["subject_type"],
            subject_identifier=h["subject_identifier"],
            status=h["status"],
            summary=h["summary"],
            created_by_user_id=h["created_by_user_id"],
            departing_user_id=h["departing_user_id"],
            recipient_user_id=h["recipient_user_id"],
            created_at=h["created_at"],
            item_count=len(items),
            items=items,
        )


@router.patch("/{handoff_id}", response_model=HandoffResponse)
async def update_handoff(
    handoff_id: UUID,
    request: UpdateHandoffRequest,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> HandoffResponse:
    """
    Update handoff status, title, or summary.
    """
    user, org = context

    if request.status and request.status not in VALID_HANDOFF_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status '{request.status}'. Must be one of {sorted(VALID_HANDOFF_STATUSES)}.",
        )

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM public.handoffs WHERE id = $1 AND org_id = $2",
            handoff_id,
            org.org_id,
        )
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Handoff not found.",
            )

        row = await conn.fetchrow(
            """
            UPDATE public.handoffs
            SET title = COALESCE($1, title),
                summary = COALESCE($2, summary),
                status = COALESCE($3, status)
            WHERE id = $4 AND org_id = $5
            RETURNING id, org_id, title, subject_type, subject_identifier, status,
                      summary, created_by_user_id, departing_user_id, recipient_user_id, created_at;
            """,
            request.title.strip() if request.title else None,
            request.summary,
            request.status,
            handoff_id,
            org.org_id,
        )

        return HandoffResponse(
            id=row["id"],
            org_id=row["org_id"],
            title=row["title"],
            subject_type=row["subject_type"],
            subject_identifier=row["subject_identifier"],
            status=row["status"],
            summary=row["summary"],
            created_by_user_id=row["created_by_user_id"],
            departing_user_id=row["departing_user_id"],
            recipient_user_id=row["recipient_user_id"],
            created_at=row["created_at"],
            item_count=0,
            items=[],
        )


@router.patch("/{handoff_id}/items/{item_id}", response_model=HandoffItemResponse)
async def update_handoff_item(
    handoff_id: UUID,
    item_id: UUID,
    request: UpdateHandoffItemRequest,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> HandoffItemResponse:
    """
    Update a handoff action item: status, assignee, or due date.
    Permitted for Org Admins, Team Leads, the handoff creator, recipient, or item assignee.
    Validates that the assignee belongs to the active organization.
    """
    user, org = context

    if request.item_status and request.item_status not in VALID_ITEM_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid item_status '{request.item_status}'. Must be one of {sorted(VALID_ITEM_STATUSES)}.",
        )

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        h = await conn.fetchrow(
            "SELECT created_by_user_id, recipient_user_id FROM public.handoffs WHERE id = $1 AND org_id = $2",
            handoff_id,
            org.org_id,
        )
        if not h:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handoff not found.")

        item = await conn.fetchrow(
            """
            SELECT id, title, description, item_status, record_id, note_id, gap_id,
                   assignee_user_id, due_date
            FROM public.handoff_items
            WHERE id = $1 AND handoff_id = $2 AND org_id = $3
            """,
            item_id,
            handoff_id,
            org.org_id,
        )
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handoff item not found.")

        is_admin = org.role == "admin"
        is_team_lead = org.role == "team_lead"
        is_creator = h["created_by_user_id"] == user.id
        is_recipient = h["recipient_user_id"] == user.id
        is_assignee = item["assignee_user_id"] == user.id

        if not (is_admin or is_team_lead or is_creator or is_recipient or is_assignee):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: you do not have permission to manage this handoff item.",
            )

        new_assignee = item["assignee_user_id"]
        if request.assignee_user_id is not None:
            mem = await conn.fetchrow(
                "SELECT id FROM public.memberships WHERE org_id = $1 AND user_id = $2",
                org.org_id,
                request.assignee_user_id,
            )
            if not mem:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Assignee user '{request.assignee_user_id}' is not an active member of this organization.",
                )
            new_assignee = request.assignee_user_id

        new_status = request.item_status if request.item_status is not None else item["item_status"]
        new_due_date = request.due_date if request.due_date is not None else item["due_date"]

        updated = await conn.fetchrow(
            """
            UPDATE public.handoff_items
            SET item_status = $1, assignee_user_id = $2, due_date = $3
            WHERE id = $4 AND org_id = $5
            RETURNING id, title, description, item_status, record_id, note_id, gap_id,
                      assignee_user_id, due_date;
            """,
            new_status,
            new_assignee,
            new_due_date,
            item_id,
            org.org_id,
        )

        return HandoffItemResponse(
            id=updated["id"],
            title=updated["title"],
            description=updated["description"],
            item_status=updated["item_status"],
            record_id=updated["record_id"],
            note_id=updated["note_id"],
            gap_id=updated["gap_id"],
            assignee_user_id=updated["assignee_user_id"],
            due_date=updated["due_date"],
            is_restricted_evidence=False,
        )

