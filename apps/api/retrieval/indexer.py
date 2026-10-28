"""
Batch embedding indexer for public.chunks.
Operates strictly under the app_sync role with transaction-scoped organization context.
Idempotently finds chunks missing vector embeddings, generates them, and updates rows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional
from uuid import UUID

import asyncpg

from apps.api.db.pool import worker_transaction_context
from apps.api.retrieval.embeddings import embed_batch, format_vector_for_pg

logger = logging.getLogger(__name__)


@dataclass
class IndexingReport:
    """Outcome of an embedding indexing / backfill run."""
    org_id: str
    chunks_scanned: int = 0
    chunks_embedded: int = 0
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class ChunkIndexer:
    """
    Service for backfilling missing embeddings in public.chunks.
    """

    async def index_missing_embeddings(
        self,
        org_id: UUID | str,
        batch_size: int = 50,
        limit: Optional[int] = None,
        connection: Optional[asyncpg.Connection] = None,
    ) -> IndexingReport:
        """
        Scan chunks with embedding IS NULL for the specified org, compute embeddings
        in batches, and update rows idempotently.
        """
        org_uuid = str(org_id)
        report = IndexingReport(org_id=org_uuid)

        if connection is not None:
            await self._run_indexing(
                connection=connection,
                org_id=org_uuid,
                batch_size=batch_size,
                limit=limit,
                report=report,
            )
        else:
            async with worker_transaction_context(org_uuid) as conn:
                await self._run_indexing(
                    connection=conn,
                    org_id=org_uuid,
                    batch_size=batch_size,
                    limit=limit,
                    report=report,
                )

        return report

    async def _run_indexing(
        self,
        connection: asyncpg.Connection,
        org_id: str,
        batch_size: int,
        limit: Optional[int],
        report: IndexingReport,
    ) -> None:
        """Internal execution inside an active app_sync transaction."""
        target_limit = limit or 1000

        # Query chunks with missing embeddings
        rows = await connection.fetch(
            """
            SELECT id, content
            FROM public.chunks
            WHERE org_id = $1 AND embedding IS NULL
            ORDER BY created_at ASC
            LIMIT $2
            """,
            UUID(org_id),
            target_limit,
        )

        report.chunks_scanned = len(rows)
        if not rows:
            logger.info("No unembedded chunks found in organization %s.", org_id)
            return

        logger.info(
            "Found %d chunks missing embeddings in organization %s. Processing in batches of %d...",
            len(rows),
            org_id,
            batch_size,
        )

        # Process in batches
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            chunk_ids = [r["id"] for r in batch]
            contents = [r["content"].strip() for r in batch]

            # Filter out any unexpectedly empty texts to avoid failure
            valid_items = []
            for cid, text in zip(chunk_ids, contents):
                if text:
                    valid_items.append((cid, text))
                else:
                    logger.warning("Skipping chunk %s with empty content", cid)

            if not valid_items:
                continue

            valid_ids = [item[0] for item in valid_items]
            valid_texts = [item[1] for item in valid_items]

            try:
                embeddings = embed_batch(valid_texts)
            except Exception as e:
                err_msg = f"Embedding batch failure: {str(e)}"
                logger.error(err_msg)
                report.errors.append(err_msg)
                continue

            # Update rows using asyncpg executemany with pgvector format
            update_data = [
                (format_vector_for_pg(vec), cid, UUID(org_id))
                for cid, vec in zip(valid_ids, embeddings)
            ]

            try:
                await connection.executemany(
                    """
                    UPDATE public.chunks
                    SET embedding = $1::extensions.vector
                    WHERE id = $2 AND org_id = $3
                    """,
                    update_data,
                )
                report.chunks_embedded += len(update_data)
            except Exception as e:
                err_msg = f"Database update failure on chunk embeddings: {str(e)}"
                logger.error(err_msg)
                report.errors.append(err_msg)

        logger.info(
            "Indexing completed: %d embedded, %d errors.",
            report.chunks_embedded,
            len(report.errors),
        )
