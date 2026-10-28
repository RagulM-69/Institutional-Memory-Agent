"""
API router for meeting transcript capture and atomic ingestion into the institutional memory.
Generates 384d vector embeddings in-memory before persisting atomically under worker context.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from apps.api.auth.dependencies import (
    ActiveOrganization,
    AuthenticatedUser,
    get_organization_context,
)
from apps.api.db.pool import transaction_context, worker_transaction_context
from apps.api.ingest.chunking import chunk_text
from apps.api.retrieval.embeddings import embed_batch, format_vector_for_pg

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])

_TICKET_RE = re.compile(r"\b([A-Z]{2,10}-\d+)\b")
_ISSUE_RE = re.compile(r"(?:^|\s)#(\d+)\b")


class IngestMeetingRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500, description="Meeting title or subject.")
    content: str = Field(..., min_length=10, description="Raw meeting transcript or synthesis.")
    meeting_date: Optional[datetime] = Field(default=None, description="Date when meeting took place.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context such as attendees or tooling.")


class IngestMeetingResponse(BaseModel):
    record_id: UUID
    source_id: UUID
    title: str
    chunk_count: int
    meeting_date: datetime
    created_at: datetime
    is_untrusted_evidence: bool = True
    status: str = "indexed"


class MeetingSummaryResponse(BaseModel):
    id: UUID
    title: str
    record_type: str
    meeting_date: Optional[str] = None
    contributed_by_user_id: Optional[str] = None
    created_at: datetime
    chunk_count: int = 0


@router.post("", response_model=IngestMeetingResponse, status_code=status.HTTP_201_CREATED)
async def ingest_meeting(
    request: IngestMeetingRequest,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> IngestMeetingResponse:
    """
    Ingest a meeting transcript into the organization's institutional knowledge store.
    1. Pre-computes chunks and 384-dimensional vector embeddings entirely in memory.
    2. Opens a single atomic transaction under worker_transaction_context (app_sync).
    3. Persists meeting source (get-or-create), record, immutable version, chunks, and cross-references.
    """
    user, org = context
    title = request.title.strip()
    content = request.content.strip()

    if not title or len(content) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Meeting title and content (at least 10 characters) are required.",
        )

    meeting_date = request.meeting_date or datetime.now(timezone.utc)

    # 1. Deterministic in-memory chunking
    chunks = chunk_text(content)
    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcript could not be chunked into valid text segments.",
        )

    # 2. In-memory pre-computation of embeddings (fails before any DB transaction)
    chunk_texts = [c.content for c in chunks]
    try:
        embeddings_raw = embed_batch(chunk_texts)
        formatted_vectors = [format_vector_for_pg(v) for v in embeddings_raw]
    except Exception as e:
        logger.exception("Failed to generate embeddings for meeting transcript: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Embedding model error: unable to generate vector representations. {e}",
        )

    # 3. Extract candidate cross-references
    candidate_refs: set[str] = set()
    for match in _TICKET_RE.finditer(content):
        candidate_refs.add(f"issue:{match.group(1).upper()}")
    for match in _ISSUE_RE.finditer(content):
        candidate_refs.add(f"issue:{match.group(1)}")

    record_id = uuid4()
    version_id = uuid4()
    version_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    external_id = f"meeting:{record_id}"

    record_metadata = {
        **request.metadata,
        "meeting_date": meeting_date.isoformat(),
        "contributed_by_user_id": str(user.id),
        "contributed_by_email": user.email,
        "is_untrusted_evidence": True,
        "evidence_type": "meeting_transcript",
    }

    # 4. Atomic database transaction under worker role (app_sync)
    async with worker_transaction_context(org_id=org.org_id) as conn:
        # Get-or-create canonical meeting source
        source_row = await conn.fetchrow(
            """
            SELECT id FROM public.sources
            WHERE org_id = $1 AND type = 'meeting' AND is_archived = false
            LIMIT 1;
            """,
            org.org_id,
        )
        if source_row:
            source_id = source_row["id"]
        else:
            source_row = await conn.fetchrow(
                """
                INSERT INTO public.sources (
                    id, org_id, name, type, visibility, config, sync_status, is_archived, created_at, updated_at
                ) VALUES (
                    gen_random_uuid(), $1, 'Meeting Transcripts', 'meeting', 'public', '{}'::jsonb, 'ok', false, now(), now()
                )
                RETURNING id;
                """,
                org.org_id,
            )
            source_id = source_row["id"]

        # Insert record
        await conn.execute(
            """
            INSERT INTO public.records (
                id, org_id, source_id, external_id, record_type, title, author_name, author_email, metadata, created_at
            ) VALUES ($1, $2, $3, $4, 'meeting', $5, $6, $7, $8::jsonb, now());
            """,
            record_id,
            org.org_id,
            source_id,
            external_id,
            title,
            user.email.split("@")[0] if user.email else "Engineer",
            user.email or "",
            json.dumps(record_metadata),
        )

        # Insert immutable record version
        await conn.execute(
            """
            INSERT INTO public.record_versions (
                id, org_id, record_id, source_id, version_index, content, content_hash, source_created_at, source_updated_at, is_latest, metadata
            ) VALUES ($1, $2, $3, $4, 1, $5, $6, $7, $7, true, $8::jsonb);
            """,
            version_id,
            org.org_id,
            record_id,
            source_id,
            content,
            version_hash,
            meeting_date,
            json.dumps(record_metadata),
        )

        # Insert chunks with pre-generated 384d embeddings
        chunk_params = [
            (
                uuid4(),
                org.org_id,
                version_id,
                record_id,
                source_id,
                chunk.chunk_index,
                chunk.content,
                chunk.token_count,
                formatted_vectors[idx],
            )
            for idx, chunk in enumerate(chunks)
        ]

        await conn.executemany(
            """
            INSERT INTO public.chunks (
                id, org_id, record_version_id, record_id, source_id, chunk_index, content, token_count, embedding
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::extensions.vector);
            """,
            chunk_params,
        )

        # Link to any matching existing records in the org
        if candidate_refs:
            matched_targets = await conn.fetch(
                """
                SELECT id FROM public.records
                WHERE org_id = $1 AND external_id = ANY($2::text[]);
                """,
                org.org_id,
                list(candidate_refs),
            )
            if matched_targets:
                link_rows = [
                    (org.org_id, record_id, t["id"], "explicit", "user_action")
                    for t in matched_targets
                ]
                await conn.executemany(
                    """
                    INSERT INTO public.record_links (
                        org_id, from_record_id, to_record_id, link_type, provenance
                    ) VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (from_record_id, to_record_id, link_type) DO NOTHING;
                    """,
                    link_rows,
                )

    return IngestMeetingResponse(
        record_id=record_id,
        source_id=source_id,
        title=title,
        chunk_count=len(chunks),
        meeting_date=meeting_date,
        created_at=datetime.now(timezone.utc),
        is_untrusted_evidence=True,
        status="indexed",
    )


@router.get("", response_model=List[MeetingSummaryResponse])
async def list_meetings(
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> List[MeetingSummaryResponse]:
    """
    List all ingested meeting transcripts for the organization.
    Runs under caller's transaction context with source access verification.
    """
    user, org = context

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        rows = await conn.fetch(
            """
            SELECT r.id, r.title, r.record_type, r.metadata, r.created_at,
                   COUNT(c.id) AS chunk_count
            FROM public.records r
            JOIN public.record_versions rv ON rv.record_id = r.id AND rv.is_latest = true
            LEFT JOIN public.chunks c ON c.record_version_id = rv.id
            WHERE r.org_id = $1
              AND r.record_type = 'meeting'
              AND public.user_can_access_source(r.source_id, $1) = true
            GROUP BY r.id, r.title, r.record_type, r.metadata, r.created_at
            ORDER BY r.created_at DESC;
            """,
            org.org_id,
        )

        result: List[MeetingSummaryResponse] = []
        for r in rows:
            meta = json.loads(r["metadata"]) if isinstance(r["metadata"], str) else (r["metadata"] or {})
            result.append(
                MeetingSummaryResponse(
                    id=r["id"],
                    title=r["title"],
                    record_type=r["record_type"],
                    meeting_date=meta.get("meeting_date"),
                    contributed_by_user_id=meta.get("contributed_by_user_id"),
                    created_at=r["created_at"],
                    chunk_count=r["chunk_count"],
                )
            )
        return result


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting(
    record_id: UUID,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> None:
    """
    Permanently delete an ingested meeting transcript and its associated chunks and versions.
    """
    user, org = context

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        rec = await conn.fetchrow(
            "SELECT id, source_id FROM public.records WHERE id = $1 AND org_id = $2 AND record_type = 'meeting'",
            record_id,
            org.org_id,
        )
        if not rec:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Meeting transcript record not found.",
            )

        # 1. Clean up knowledge note links
        await conn.execute(
            "DELETE FROM public.knowledge_note_records WHERE record_id = $1 AND org_id = $2",
            record_id,
            org.org_id,
        )

        # 2. Clean up record links
        await conn.execute(
            """
            DELETE FROM public.record_links
            WHERE (from_record_id = $1 OR to_record_id = $1) AND org_id = $2
            """,
            record_id,
            org.org_id,
        )

        # 3. Clean up chunks
        await conn.execute(
            "DELETE FROM public.chunks WHERE record_id = $1 AND org_id = $2",
            record_id,
            org.org_id,
        )

        # 4. Clean up versions
        await conn.execute(
            "DELETE FROM public.record_versions WHERE record_id = $1 AND org_id = $2",
            record_id,
            org.org_id,
        )

        # 5. Clean up record
        await conn.execute(
            "DELETE FROM public.records WHERE id = $1 AND org_id = $2",
            record_id,
            org.org_id,
        )
