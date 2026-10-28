"""
Permission-aware semantic retrieval service for Institutional Memory Agent.
Executes vector similarity search under app_runtime role with user- and org-scoped RLS.
Returns exact verbatim evidence chunks with full provenance and version attribution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from uuid import UUID

import asyncpg

from apps.api.db.pool import transaction_context
from apps.api.retrieval.embeddings import embed_text, format_vector_for_pg

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvidenceChunk:
    """Verbatim evidence chunk with source provenance and version attribution."""
    chunk_id: str
    content: str
    chunk_index: int
    token_count: int
    record_id: str
    record_version_id: str
    source_id: str
    record_title: str
    record_type: str
    record_url: Optional[str]
    author_name: Optional[str]
    version_index: int
    source_created_at: datetime
    source_updated_at: datetime
    cosine_distance: float


class SemanticRetriever:
    """
    Retrieves evidence chunks relevant to a natural language query
    while strictly enforcing database-level tenant and source access boundaries.
    """

    async def search(
        self,
        user_id: UUID | str,
        org_id: UUID | str,
        query: str,
        limit: int = 5,
        connection: Optional[asyncpg.Connection] = None,
    ) -> List[EvidenceChunk]:
        """
        Execute vector similarity search across accessible evidence chunks.
        Never returns data outside the user's verified organization and permitted sources.
        """
        clean_query = query.strip() if query else ""
        if not clean_query:
            return []

        # Bound result limit defensively (1 to 50)
        bounded_limit = max(1, min(limit, 50))
        user_uuid = str(user_id)
        org_uuid = str(org_id)

        # Generate query vector (384 dimensions)
        query_vector = embed_text(clean_query)
        vector_str = format_vector_for_pg(query_vector)

        if connection is not None:
            return await self._run_query(
                connection=connection,
                vector_str=vector_str,
                limit=bounded_limit,
            )
        else:
            # Execute within runtime pool with user and org transaction session context
            async with transaction_context(user_id=user_uuid, org_id=org_uuid) as conn:
                return await self._run_query(
                    connection=conn,
                    vector_str=vector_str,
                    limit=bounded_limit,
                )

    async def _run_query(
        self,
        connection: asyncpg.Connection,
        vector_str: str,
        limit: int,
    ) -> List[EvidenceChunk]:
        """Run parameterized similarity query through RLS-filtered views."""
        rows = await connection.fetch(
            """
            SELECT
                c.id AS chunk_id,
                c.content AS chunk_content,
                c.chunk_index,
                c.token_count,
                c.record_id,
                c.record_version_id,
                c.source_id,
                (c.embedding OPERATOR(extensions.<=>) $1::extensions.vector) AS cosine_distance,
                r.title AS record_title,
                r.record_type,
                r.url AS record_url,
                r.author_name,
                rv.version_index,
                rv.source_created_at,
                rv.source_updated_at
            FROM public.chunks c
            JOIN public.records r 
              ON r.id = c.record_id AND r.org_id = c.org_id
            JOIN public.record_versions rv 
              ON rv.id = c.record_version_id AND rv.org_id = c.org_id
            WHERE c.embedding IS NOT NULL
            ORDER BY c.embedding OPERATOR(extensions.<=>) $1::extensions.vector ASC
            LIMIT $2;
            """,
            vector_str,
            limit,
        )

        return [
            EvidenceChunk(
                chunk_id=str(r["chunk_id"]),
                content=r["chunk_content"],
                chunk_index=r["chunk_index"],
                token_count=r["token_count"],
                record_id=str(r["record_id"]),
                record_version_id=str(r["record_version_id"]),
                source_id=str(r["source_id"]),
                record_title=r["record_title"],
                record_type=r["record_type"],
                record_url=r["record_url"],
                author_name=r["author_name"],
                version_index=r["version_index"],
                source_created_at=r["source_created_at"],
                source_updated_at=r["source_updated_at"],
                cosine_distance=float(r["cosine_distance"]),
            )
            for r in rows
        ]
