"""
Comprehensive tests for 384-dimensional local embeddings,
idempotent batch indexing, and permission-aware semantic retrieval.
Includes unit tests with mocked DB/model and live integration tests against Supabase PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import asyncpg
import pytest

from apps.api.config import settings
from apps.api.retrieval.embeddings import (
    EMBEDDING_DIM,
    embed_batch,
    embed_text,
    format_vector_for_pg,
)
from apps.api.retrieval.indexer import ChunkIndexer, IndexingReport
from apps.api.retrieval.search import EvidenceChunk, SemanticRetriever


# ─────────────────────────────────────────────────────────────────────────────
# 1. Local Embeddings Unit Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_embedding_dimensions():
    """Verify local model outputs exactly 384-dimensional vector."""
    vec = embed_text("Institutional memory for engineering teams.")
    assert isinstance(vec, list)
    assert len(vec) == EMBEDDING_DIM
    assert all(isinstance(x, float) for x in vec)


def test_embedding_batch_processing():
    """Verify batch processing produces matching 384-dimensional vectors."""
    texts = [
        "First architectural decision note.",
        "Second rationale regarding database pooling.",
    ]
    vectors = embed_batch(texts)
    assert len(vectors) == 2
    assert len(vectors[0]) == EMBEDDING_DIM
    assert len(vectors[1]) == EMBEDDING_DIM


def test_embedding_empty_text_rejected():
    """Ensure empty or whitespace-only inputs are rejected (never embedded)."""
    with pytest.raises(ValueError, match="empty or whitespace-only"):
        embed_text("")
    with pytest.raises(ValueError, match="empty or whitespace-only"):
        embed_text("   \n\t  ")


def test_embedding_batch_empty_item_rejected():
    """Ensure batches with empty items fail closed."""
    with pytest.raises(ValueError, match="Empty or whitespace-only"):
        embed_batch(["Valid text", "", "Another valid text"])


def test_format_vector_for_pg():
    """Verify pgvector formatting: [x,y,z]."""
    vec = [0.123, -0.456, 0.789]
    formatted = format_vector_for_pg(vec)
    assert formatted.startswith("[") and formatted.endswith("]")
    assert "0.123" in formatted
    assert "-0.456" in formatted


# ─────────────────────────────────────────────────────────────────────────────
# 2. Chunk Indexer Unit Tests (Mocked DB)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_indexer_idempotent_backfill():
    """Verify indexer queries unembedded chunks, batches them, and updates embedding column."""
    indexer = ChunkIndexer()
    mock_conn = AsyncMock()
    org_id = uuid4()
    chunk1_id = uuid4()
    chunk2_id = uuid4()

    # Chunks returned on first call
    mock_conn.fetch.return_value = [
        {"id": chunk1_id, "content": "Chunk 1 content describing webhooks."},
        {"id": chunk2_id, "content": "Chunk 2 content describing polling fallback."},
    ]

    report = await indexer.index_missing_embeddings(
        org_id=org_id,
        batch_size=50,
        connection=mock_conn,
    )

    assert report.chunks_scanned == 2
    assert report.chunks_embedded == 2
    assert len(report.errors) == 0

    # Verify executemany was called to update chunks
    assert mock_conn.executemany.call_count == 1
    call_args = mock_conn.executemany.call_args[0]
    sql, update_data = call_args[0], call_args[1]
    assert "UPDATE public.chunks" in sql
    assert len(update_data) == 2
    assert update_data[0][1] == chunk1_id
    assert update_data[0][2] == org_id


@pytest.mark.asyncio
async def test_indexer_handles_embedding_failure():
    """Ensure embedding batch failure logs errors and does not corrupt database state."""
    indexer = ChunkIndexer()
    mock_conn = AsyncMock()
    org_id = uuid4()

    mock_conn.fetch.return_value = [
        {"id": uuid4(), "content": "Sample content"},
    ]

    with patch("apps.api.retrieval.indexer.embed_batch", side_effect=RuntimeError("Model inference failed")):
        report = await indexer.index_missing_embeddings(
            org_id=org_id,
            connection=mock_conn,
        )

    assert report.chunks_scanned == 1
    assert report.chunks_embedded == 0
    assert len(report.errors) == 1
    assert "Model inference failed" in report.errors[0]
    assert mock_conn.executemany.call_count == 0


@pytest.mark.asyncio
async def test_indexer_skips_empty_chunks():
    """Ensure whitespace-only chunks are skipped without crashing the batch."""
    indexer = ChunkIndexer()
    mock_conn = AsyncMock()
    org_id = uuid4()

    mock_conn.fetch.return_value = [
        {"id": uuid4(), "content": "   \n  "},
    ]

    report = await indexer.index_missing_embeddings(
        org_id=org_id,
        connection=mock_conn,
    )

    assert report.chunks_scanned == 1
    assert report.chunks_embedded == 0
    assert len(report.errors) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Semantic Retriever Unit Tests (Mocked DB)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retriever_query_and_attribution():
    """Verify retriever maps DB rows into EvidenceChunk preserving verbatim text and attribution."""
    retriever = SemanticRetriever()
    mock_conn = AsyncMock()
    user_id = uuid4()
    org_id = uuid4()
    chunk_id = uuid4()
    record_id = uuid4()
    version_id = uuid4()
    source_id = uuid4()

    now = datetime.now(timezone.utc)
    mock_conn.fetch.return_value = [
        {
            "chunk_id": chunk_id,
            "chunk_content": "Supplier API drops webhooks under peak traffic without retrying.",
            "chunk_index": 0,
            "token_count": 12,
            "record_id": record_id,
            "record_version_id": version_id,
            "source_id": source_id,
            "cosine_distance": 0.1425,
            "record_title": "[PROJ-101] Implement polling fallback",
            "record_type": "ticket",
            "record_url": "https://company.atlassian.net/browse/PROJ-101",
            "author_name": "Alice Lead",
            "version_index": 2,
            "source_created_at": now,
            "source_updated_at": now,
        }
    ]

    results = await retriever.search(
        user_id=user_id,
        org_id=org_id,
        query="Why do we use polling for orders?",
        limit=5,
        connection=mock_conn,
    )

    assert len(results) == 1
    c = results[0]
    assert c.chunk_id == str(chunk_id)
    assert c.content == "Supplier API drops webhooks under peak traffic without retrying."
    assert c.record_title == "[PROJ-101] Implement polling fallback"
    assert c.record_type == "ticket"
    assert c.record_url == "https://company.atlassian.net/browse/PROJ-101"
    assert c.author_name == "Alice Lead"
    assert c.version_index == 2
    assert c.cosine_distance == pytest.approx(0.1425, abs=1e-4)


@pytest.mark.asyncio
async def test_retriever_empty_query():
    """Verify empty query returns empty list without calling DB."""
    retriever = SemanticRetriever()
    mock_conn = AsyncMock()
    results = await retriever.search(
        user_id=uuid4(),
        org_id=uuid4(),
        query="   ",
        connection=mock_conn,
    )
    assert results == []
    assert mock_conn.fetch.call_count == 0


@pytest.mark.asyncio
async def test_retriever_empty_results_when_unauthorized():
    """Verify empty result when no authorized chunks match (honest abstention foundation)."""
    retriever = SemanticRetriever()
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []

    results = await retriever.search(
        user_id=uuid4(),
        org_id=uuid4(),
        query="unauthorized confidential data",
        connection=mock_conn,
    )
    assert results == []


@pytest.mark.asyncio
async def test_retriever_bounds_limit():
    """Verify query limit is bounded defensively."""
    retriever = SemanticRetriever()
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []

    # Limit = 200 clamped to 50
    await retriever.search(
        user_id=uuid4(),
        org_id=uuid4(),
        query="test query",
        limit=200,
        connection=mock_conn,
    )
    passed_limit = mock_conn.fetch.call_args[0][2]
    assert passed_limit == 50


# ─────────────────────────────────────────────────────────────────────────────
# 4. Live Supabase PostgreSQL Integration Tests
# ─────────────────────────────────────────────────────────────────────────────

DATABASE_URL = settings.database_url.get_secret_value()
WORKER_DATABASE_URL = settings.worker_database_url.get_secret_value()


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
@pytest.mark.asyncio
async def test_live_retrieval_empty_for_nonexistent_tenant():
    """
    Execute live vector similarity query on Supabase PostgreSQL.
    Verifies that RLS and vector search execute without errors and fail closed (return 0 rows).
    """
    retriever = SemanticRetriever()
    random_user = uuid4()
    random_org = uuid4()

    results = await retriever.search(
        user_id=random_user,
        org_id=random_org,
        query="order service polling architecture",
        limit=5,
    )
    assert results == []


@pytest.mark.skipif(not WORKER_DATABASE_URL, reason="WORKER_DATABASE_URL is not configured")
@pytest.mark.asyncio
async def test_live_app_sync_chunks_embedding_update_policy():
    """
    Verify on live Supabase that app_sync has column-level UPDATE on chunks(embedding)
    and that migration 003 policy chunks_worker_update_policy enforces tenant RLS.
    """
    conn = await asyncpg.connect(WORKER_DATABASE_URL, ssl="require", statement_cache_size=0)
    try:
        test_org = str(uuid4())
        nonexistent_chunk_id = str(uuid4())

        async with conn.transaction():
            # Set org context
            await conn.execute("SELECT set_config('app.current_org_id', $1, true)", test_org)

            # This UPDATE statement previously threw InsufficientPrivilegeError before migration 003!
            # Now it must succeed cleanly (updating 0 rows because the ID does not exist).
            sample_vector = "[" + ",".join(["0.0"] * 384) + "]"
            result = await conn.execute(
                """
                UPDATE public.chunks
                SET embedding = $1::extensions.vector
                WHERE id = $2 AND org_id = $3
                """,
                sample_vector,
                UUID(nonexistent_chunk_id),
                UUID(test_org),
            )
            assert result == "UPDATE 0"

            # Verify that app_sync CANNOT update any other column (e.g. content or token_count)
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute(
                    """
                    UPDATE public.chunks
                    SET content = 'unauthorized modification'
                    WHERE id = $1 AND org_id = $2
                    """,
                    UUID(nonexistent_chunk_id),
                    UUID(test_org),
                )

    finally:
        await conn.close()

