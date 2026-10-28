"""
API router for human-attributed knowledge capture and note-record linking.
Provides endpoints for creating, retrieving, and managing personal knowledge notes.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from apps.api.auth.dependencies import (
    ActiveOrganization,
    AuthenticatedUser,
    get_organization_context,
)
from apps.api.db.pool import transaction_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge-notes", tags=["knowledge"])


class LinkedRecordSummary(BaseModel):
    id: UUID
    title: str
    record_type: str
    external_id: str


class CreateKnowledgeNoteRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500, description="Title of the knowledge note.")
    content: str = Field(..., min_length=1, description="Markdown body explaining rationale, context, or bridge knowledge.")
    record_ids: List[UUID] = Field(default_factory=list, description="Optional source records to link.")


class KnowledgeNoteResponse(BaseModel):
    id: UUID
    org_id: UUID
    author_user_id: Optional[UUID] = None
    title: str
    content: str
    status: str
    is_human_contributed: bool = True
    created_at: datetime
    updated_at: datetime
    linked_records: List[LinkedRecordSummary] = Field(default_factory=list)


@router.post("", response_model=KnowledgeNoteResponse, status_code=status.HTTP_201_CREATED)
async def create_knowledge_note(
    request: CreateKnowledgeNoteRequest,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> KnowledgeNoteResponse:
    """
    Create a new human-contributed knowledge note with optional links to existing source records.
    Validates tenant isolation and caller source access for all linked records before persistence.
    """
    user, org = context
    title = request.title.strip()
    content = request.content.strip()

    if not title or not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Title and content must not be empty or whitespace only.",
        )

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        # Validate that caller can access all linked records
        valid_records: List[LinkedRecordSummary] = []
        if request.record_ids:
            # Query source and access for each record
            for record_id in request.record_ids:
                row = await conn.fetchrow(
                    """
                    SELECT r.id, r.title, r.record_type, r.external_id, r.source_id,
                           public.user_can_access_source(r.source_id, $2) AS has_access
                    FROM public.records r
                    WHERE r.id = $1 AND r.org_id = $2
                    """,
                    record_id,
                    org.org_id,
                )
                if not row:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Record '{record_id}' not found in the current organization.",
                    )
                if not row["has_access"]:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Access denied: you do not have permission to view source record '{record_id}'.",
                    )
                valid_records.append(
                    LinkedRecordSummary(
                        id=row["id"],
                        title=row["title"],
                        record_type=row["record_type"],
                        external_id=row["external_id"],
                    )
                )

        # Insert knowledge note
        note_row = await conn.fetchrow(
            """
            INSERT INTO public.knowledge_notes (
                org_id, author_user_id, title, content, status
            ) VALUES ($1, $2, $3, $4, 'personal')
            RETURNING id, org_id, author_user_id, title, content, status, created_at, updated_at;
            """,
            org.org_id,
            user.id,
            title,
            content,
        )

        note_id = note_row["id"]

        # Insert record links
        if valid_records:
            await conn.executemany(
                """
                INSERT INTO public.knowledge_note_records (
                    org_id, note_id, record_id
                ) VALUES ($1, $2, $3)
                ON CONFLICT (note_id, record_id, org_id) DO NOTHING;
                """,
                [(org.org_id, note_id, r.id) for r in valid_records],
            )

        return KnowledgeNoteResponse(
            id=note_row["id"],
            org_id=note_row["org_id"],
            author_user_id=note_row["author_user_id"],
            title=note_row["title"],
            content=note_row["content"],
            status=note_row["status"],
            is_human_contributed=True,
            created_at=note_row["created_at"],
            updated_at=note_row["updated_at"],
            linked_records=valid_records,
        )


@router.get("", response_model=List[KnowledgeNoteResponse])
async def list_knowledge_notes(
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> List[KnowledgeNoteResponse]:
    """
    List all knowledge notes for the active organization.
    Filters linked records so that unauthorized records are never leaked to caller.
    """
    user, org = context

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        notes = await conn.fetch(
            """
            SELECT id, org_id, author_user_id, title, content, status, created_at, updated_at
            FROM public.knowledge_notes
            WHERE org_id = $1
            ORDER BY created_at DESC;
            """,
            org.org_id,
        )

        if not notes:
            return []

        note_ids = [n["id"] for n in notes]

        # Fetch linked records accessible to caller
        links = await conn.fetch(
            """
            SELECT knr.note_id, r.id, r.title, r.record_type, r.external_id
            FROM public.knowledge_note_records knr
            JOIN public.records r ON r.id = knr.record_id AND r.org_id = knr.org_id
            WHERE knr.note_id = ANY($1::uuid[])
              AND knr.org_id = $2
              AND public.user_can_access_source(r.source_id, $2) = true;
            """,
            note_ids,
            org.org_id,
        )

        records_by_note: dict[UUID, List[LinkedRecordSummary]] = {}
        for row in links:
            records_by_note.setdefault(row["note_id"], []).append(
                LinkedRecordSummary(
                    id=row["id"],
                    title=row["title"],
                    record_type=row["record_type"],
                    external_id=row["external_id"],
                )
            )

        return [
            KnowledgeNoteResponse(
                id=n["id"],
                org_id=n["org_id"],
                author_user_id=n["author_user_id"],
                title=n["title"],
                content=n["content"],
                status=n["status"],
                is_human_contributed=True,
                created_at=n["created_at"],
                updated_at=n["updated_at"],
                linked_records=records_by_note.get(n["id"], []),
            )
            for n in notes
        ]


@router.get("/{note_id}", response_model=KnowledgeNoteResponse)
async def get_knowledge_note(
    note_id: UUID,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> KnowledgeNoteResponse:
    """
    Get a single knowledge note by ID with accessible linked records.
    """
    user, org = context

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        n = await conn.fetchrow(
            """
            SELECT id, org_id, author_user_id, title, content, status, created_at, updated_at
            FROM public.knowledge_notes
            WHERE id = $1 AND org_id = $2;
            """,
            note_id,
            org.org_id,
        )

        if not n:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Knowledge note not found.",
            )

        links = await conn.fetch(
            """
            SELECT r.id, r.title, r.record_type, r.external_id
            FROM public.knowledge_note_records knr
            JOIN public.records r ON r.id = knr.record_id AND r.org_id = knr.org_id
            WHERE knr.note_id = $1
              AND knr.org_id = $2
              AND public.user_can_access_source(r.source_id, $2) = true;
            """,
            note_id,
            org.org_id,
        )

        linked_records = [
            LinkedRecordSummary(
                id=row["id"],
                title=row["title"],
                record_type=row["record_type"],
                external_id=row["external_id"],
            )
            for row in links
        ]

        return KnowledgeNoteResponse(
            id=n["id"],
            org_id=n["org_id"],
            author_user_id=n["author_user_id"],
            title=n["title"],
            content=n["content"],
            status=n["status"],
            is_human_contributed=True,
            created_at=n["created_at"],
            updated_at=n["updated_at"],
            linked_records=linked_records,
        )


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_note(
    note_id: UUID,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> None:
    """
    Permanently delete a knowledge note and its linked record references.
    """
    user, org = context

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        note = await conn.fetchrow(
            "SELECT id FROM public.knowledge_notes WHERE id = $1 AND org_id = $2",
            note_id,
            org.org_id,
        )
        if not note:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Knowledge note not found.",
            )

        # 1. Delete linked record relations
        await conn.execute(
            "DELETE FROM public.knowledge_note_records WHERE note_id = $1 AND org_id = $2",
            note_id,
            org.org_id,
        )

        # 2. Delete note
        await conn.execute(
            "DELETE FROM public.knowledge_notes WHERE id = $1 AND org_id = $2",
            note_id,
            org.org_id,
        )

