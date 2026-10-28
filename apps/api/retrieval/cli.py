"""
Command Line Interface for Embedding Indexing and Permission-Aware Semantic Retrieval.

Usage:
    # 1. Backfill missing embeddings:
    python -m apps.api.retrieval.cli backfill --org-id <uuid> [--batch-size 50] [--limit 500]

    # 2. Search evidence chunks:
    python -m apps.api.retrieval.cli search --query "order polling" --org-id <uuid> --user-id <uuid> [--limit 5]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from uuid import UUID

from apps.api.db.pool import close_pool
from apps.api.retrieval.indexer import ChunkIndexer
from apps.api.retrieval.search import SemanticRetriever

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("handoff.retrieval.cli")


async def run_backfill(args: argparse.Namespace) -> int:
    try:
        org_id = UUID(args.org_id)
    except ValueError:
        logger.error("Invalid org-id UUID: %s", args.org_id)
        return 1

    indexer = ChunkIndexer()
    logger.info("Starting embedding backfill for organization %s...", org_id)
    report = await indexer.index_missing_embeddings(
        org_id=org_id,
        batch_size=args.batch_size,
        limit=args.limit,
    )

    logger.info(
        "Backfill completed: %d scanned, %d embedded, %d errors.",
        report.chunks_scanned,
        report.chunks_embedded,
        len(report.errors),
    )
    if report.errors:
        for err in report.errors:
            logger.warning("Error: %s", err)
        return 2
    return 0


async def run_search(args: argparse.Namespace) -> int:
    try:
        org_id = UUID(args.org_id)
    except ValueError:
        logger.error("Invalid org-id UUID: %s", args.org_id)
        return 1

    try:
        user_id = UUID(args.user_id)
    except ValueError:
        logger.error("Invalid user-id UUID: %s", args.user_id)
        return 1

    query = args.query.strip()
    if not query:
        logger.error("Query cannot be empty.")
        return 1

    retriever = SemanticRetriever()
    logger.info("Executing retrieval for query: '%s' (org: %s, user: %s)...", query, org_id, user_id)
    results = await retriever.search(
        user_id=user_id,
        org_id=org_id,
        query=query,
        limit=args.limit,
    )

    if not results:
        logger.info("No authorized evidence chunks found matching the query.")
        return 0

    logger.info("Found %d evidence chunk(s):\n", len(results))
    for idx, chunk in enumerate(results, 1):
        print(f"--- [Result {idx}] (Distance: {chunk.cosine_distance:.4f}) ---")
        print(f"Record: [{chunk.record_type}] {chunk.record_title}")
        print(f"URL: {chunk.record_url or 'N/A'}")
        print(f"Author: {chunk.author_name or 'N/A'} | Version: v{chunk.version_index}")
        print(f"Created: {chunk.source_created_at.isoformat()}")
        print(f"Chunk Index: {chunk.chunk_index} ({chunk.token_count} tokens)")
        print("\nVerbatim Content:")
        print(chunk.content)
        print("-" * 60 + "\n")

    return 0


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="Handoff Semantic Retrieval & Indexing CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: backfill
    p_backfill = subparsers.add_parser("backfill", help="Backfill missing chunk embeddings")
    p_backfill.add_argument("--org-id", required=True, help="Organization UUID")
    p_backfill.add_argument("--batch-size", type=int, default=50, help="Batch size for embedding generation")
    p_backfill.add_argument("--limit", type=int, default=None, help="Maximum chunks to process")

    # Subcommand: search
    p_search = subparsers.add_parser("search", help="Execute permission-aware vector search")
    p_search.add_argument("--query", required=True, help="Search query string")
    p_search.add_argument("--org-id", required=True, help="Organization UUID")
    p_search.add_argument("--user-id", required=True, help="Authenticated User UUID")
    p_search.add_argument("--limit", type=int, default=5, help="Maximum results to return")

    parsed_args = parser.parse_args()

    exit_code = 0
    try:
        if parsed_args.command == "backfill":
            exit_code = await run_backfill(parsed_args)
        elif parsed_args.command == "search":
            exit_code = await run_search(parsed_args)
    finally:
        await close_pool()

    return exit_code


def main() -> None:
    sys.exit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()

