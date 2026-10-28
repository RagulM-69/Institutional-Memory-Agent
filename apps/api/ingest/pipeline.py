"""
Evidence ingestion pipeline for Institutional Memory Agent.
Orchestrates connector fetch, record normalization, version immutability,
chunking, link resolution, and source status synchronization.
Runs strictly under the app_sync role with transaction-local org isolation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import asyncpg

from apps.api.auth.crypto import decrypt_credentials, DecryptionError
from apps.api.connectors.base import BaseConnector, ExtractedLink, FetchResult, NormalizedRecord
from apps.api.connectors.github import GitHubConnector
from apps.api.connectors.jira import JiraConnector
from apps.api.connectors.slack import SlackConnector
from apps.api.db.pool import worker_transaction_context
from apps.api.ingest.chunking import chunk_text

logger = logging.getLogger(__name__)


@dataclass
class SyncReport:
    """Detailed outcome of an ingestion pipeline run."""
    source_id: str
    org_id: str
    status: str  # 'ok', 'partial', 'failed'
    records_scanned: int = 0
    records_created: int = 0
    records_updated: int = 0
    versions_created: int = 0
    chunks_created: int = 0
    links_created: int = 0
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


def compute_content_hash(content: str) -> str:
    """Compute deterministic SHA-256 hash of record content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class IngestPipeline:
    """
    Ingestion processor enforcing tenant containment and evidence immutability.
    """

    async def sync_source(
        self,
        source_id: UUID | str,
        org_id: UUID | str,
        limit: Optional[int] = None,
        connector: Optional[BaseConnector] = None,
        connection: Optional[asyncpg.Connection] = None,
    ) -> SyncReport:
        """
        Execute an end-to-end sync cycle for a registered source.
        """
        source_uuid = str(source_id)
        org_uuid = str(org_id)
        start_time = time.monotonic()
        report = SyncReport(source_id=source_uuid, org_id=org_uuid, status="running")

        # Use provided connection or acquire worker transaction context
        if connection is not None:
            report = await self._run_sync(
                connection=connection,
                source_id=source_uuid,
                org_id=org_uuid,
                limit=limit,
                connector=connector,
                report=report,
            )
        else:
            async with worker_transaction_context(org_uuid) as conn:
                report = await self._run_sync(
                    connection=conn,
                    source_id=source_uuid,
                    org_id=org_uuid,
                    limit=limit,
                    connector=connector,
                    report=report,
                )

        report.duration_seconds = round(time.monotonic() - start_time, 3)
        return report

    async def _run_sync(
        self,
        connection: asyncpg.Connection,
        source_id: str,
        org_id: str,
        limit: Optional[int],
        connector: Optional[BaseConnector],
        report: SyncReport,
    ) -> SyncReport:
        """Internal execution within verified app_sync context."""
        # 1. Load and lock source row
        source_row = await connection.fetchrow(
            """
            SELECT id, name, type, config, encrypted_credentials, sync_cursor, sync_status
            FROM public.sources
            WHERE id = $1 AND org_id = $2
            FOR UPDATE
            """,
            UUID(source_id),
            UUID(org_id),
        )

        if not source_row:
            report.status = "failed"
            report.errors.append(f"Source {source_id} not found in organization {org_id}")
            return report

        source_type = source_row["type"]
        raw_config = source_row["config"]
        config = json.loads(raw_config) if isinstance(raw_config, str) else (raw_config or {})
        raw_cursor = source_row["sync_cursor"]
        sync_cursor = json.loads(raw_cursor) if isinstance(raw_cursor, str) else (raw_cursor or {})
        raw_enc = source_row.get("encrypted_credentials")

        # Decrypt per-organization / per-source credentials if stored
        source_credentials: Optional[Dict[str, Any]] = None
        if raw_enc:
            try:
                decrypted = decrypt_credentials(raw_enc, org_id, source_id)
                if isinstance(decrypted, dict):
                    source_credentials = decrypted
                elif isinstance(decrypted, str):
                    source_credentials = {"token": decrypted}
            except DecryptionError as de:
                logger.error("Failed to decrypt credentials for source %s: %s", source_id, de)
                report.status = "failed"
                report.errors.append("Decryption failed: stored credentials could not be verified.")
                await self._update_source_status(connection, source_id, org_id, "failed", sync_cursor, report.errors)
                return report

        # Mark source as running
        await connection.execute(
            """
            UPDATE public.sources
            SET sync_status = 'running', updated_at = now()
            WHERE id = $1 AND org_id = $2
            """,
            UUID(source_id),
            UUID(org_id),
        )

        # 2. Instantiate connector if not injected
        if connector is None:
            if source_type == "github":
                repo = config.get("repo")
                if not repo:
                    report.status = "failed"
                    report.errors.append("GitHub source config missing 'repo' key (e.g. 'owner/repo')")
                    await self._update_source_status(connection, source_id, org_id, "failed", sync_cursor, report.errors)
                    return report
                token = source_credentials.get("token") if source_credentials else None
                connector = GitHubConnector(repo=repo, token=token)
            elif source_type == "jira":
                base_url = config.get("base_url")
                project = config.get("project")
                jql = config.get("jql")
                email = source_credentials.get("email") if source_credentials else None
                token = source_credentials.get("token") if source_credentials else None
                try:
                    connector = JiraConnector(
                        base_url=base_url,
                        email=email,
                        token=token,
                        project=project,
                        jql=jql,
                    )
                except ValueError as ve:
                    report.status = "failed"
                    report.errors.append(f"Jira configuration error: {str(ve)}")
                    await self._update_source_status(connection, source_id, org_id, "failed", sync_cursor, report.errors)
                    return report
            elif source_type == "slack":
                channel_id = config.get("channel_id")
                if not channel_id:
                    report.status = "failed"
                    report.errors.append("Slack source config missing 'channel_id' key")
                    await self._update_source_status(connection, source_id, org_id, "failed", sync_cursor, report.errors)
                    return report
                token = (source_credentials.get("token") if source_credentials else None) or config.get("token")
                try:
                    connector = SlackConnector(channel_id=channel_id, token=token)
                except ValueError as ve:
                    report.status = "failed"
                    report.errors.append(f"Slack configuration error: {str(ve)}")
                    await self._update_source_status(connection, source_id, org_id, "failed", sync_cursor, report.errors)
                    return report
                    return report
            else:
                report.status = "failed"
                report.errors.append(f"Connector type '{source_type}' is not supported yet")
                await self._update_source_status(connection, source_id, org_id, "failed", sync_cursor, report.errors)
                return report

        # 3. Fetch from connector
        try:
            fetch_result = await connector.fetch(cursor=sync_cursor, limit=limit)
        except Exception as e:
            logger.exception("Connector fetch failed for source %s", source_id)
            report.status = "failed"
            report.errors.append(f"Fetch failure: {str(e)}")
            await self._update_source_status(connection, source_id, org_id, "failed", sync_cursor, report.errors)
            return report

        report.records_scanned = len(fetch_result.records)
        if fetch_result.errors:
            report.errors.extend(fetch_result.errors)

        # 4. Ingest normalized records
        pending_links: List[Tuple[UUID, ExtractedLink]] = []

        for rec in fetch_result.records:
            try:
                record_id, is_new = await self._upsert_record(
                    connection=connection,
                    source_id=UUID(source_id),
                    org_id=UUID(org_id),
                    rec=rec,
                )
                if is_new:
                    report.records_created += 1
                else:
                    report.records_updated += 1

                version_created, chunks_count = await self._process_version_and_chunks(
                    connection=connection,
                    source_id=UUID(source_id),
                    org_id=UUID(org_id),
                    record_id=record_id,
                    rec=rec,
                )
                if version_created:
                    report.versions_created += 1
                report.chunks_created += chunks_count

                # Collect links for batch resolution
                for link in rec.extracted_links:
                    pending_links.append((record_id, link))

            except Exception as e:
                logger.exception("Failed processing record %s for source %s", rec.external_id, source_id)
                report.errors.append(f"Record {rec.external_id}: {str(e)}")

        # 5. Resolve cross-references into record_links
        if pending_links:
            resolved_links = await self._resolve_links(
                connection=connection,
                source_id=UUID(source_id),
                org_id=UUID(org_id),
                pending_links=pending_links,
            )
            report.links_created = resolved_links

        # 5b. Index vector embeddings for newly inserted chunks
        try:
            from apps.api.retrieval.indexer import ChunkIndexer
            indexer = ChunkIndexer()
            idx_report = await indexer.index_missing_embeddings(
                org_id=UUID(org_id),
                connection=connection,
            )
            logger.info("Indexed %d chunk embeddings for org %s", idx_report.chunks_embedded, org_id)
        except Exception as ie:
            logger.warning("Failed to auto-index chunk embeddings for org %s: %s", org_id, ie)

        # 6. Update source status and cursor
        status = "partial" if report.errors else "ok"
        report.status = status
        await self._update_source_status(
            connection=connection,
            source_id=source_id,
            org_id=org_id,
            status=status,
            new_cursor=fetch_result.new_cursor,
            errors=report.errors,
        )

        return report

    async def _upsert_record(
        self,
        connection: asyncpg.Connection,
        source_id: UUID,
        org_id: UUID,
        rec: NormalizedRecord,
    ) -> Tuple[UUID, bool]:
        """
        Upsert into public.records.
        Returns (record_id, is_new).
        """
        row = await connection.fetchrow(
            """
            INSERT INTO public.records (
                org_id, source_id, external_id, record_type,
                title, url, author_name, author_email,
                is_deleted_upstream, metadata
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, $7, $8,
                $9, $10::jsonb
            )
            ON CONFLICT (source_id, external_id) DO UPDATE SET
                title = EXCLUDED.title,
                url = EXCLUDED.url,
                author_name = EXCLUDED.author_name,
                author_email = EXCLUDED.author_email,
                is_deleted_upstream = EXCLUDED.is_deleted_upstream,
                metadata = EXCLUDED.metadata
            RETURNING id, (xmax = 0) AS is_new;
            """,
            org_id,
            source_id,
            rec.external_id,
            rec.record_type,
            rec.title,
            rec.url,
            rec.author_name,
            rec.author_email,
            rec.is_deleted_upstream,
            json.dumps(rec.metadata),
        )
        return row["id"], row["is_new"]

    async def _process_version_and_chunks(
        self,
        connection: asyncpg.Connection,
        source_id: UUID,
        org_id: UUID,
        record_id: UUID,
        rec: NormalizedRecord,
    ) -> Tuple[bool, int]:
        """
        Compare content hash with latest version.
        If hash is unchanged, skip insertion (idempotent).
        If hash is different or no previous version exists, append a new version
        and generate chunks.
        Returns (version_created: bool, chunks_created: int).
        """
        content_hash = compute_content_hash(rec.content)

        latest_version = await connection.fetchrow(
            """
            SELECT id, version_index, content_hash
            FROM public.record_versions
            WHERE record_id = $1 AND org_id = $2 AND is_latest = true
            """,
            record_id,
            org_id,
        )

        if latest_version and latest_version["content_hash"] == content_hash:
            # Content is identical to latest version; skip version insert and chunking
            return False, 0

        next_version_index = (latest_version["version_index"] + 1) if latest_version else 1

        # Inserting with is_latest = true automatically fires the database trigger
        # `trg_retire_previous_record_version`, which sets the previous latest version to false.
        version_row = await connection.fetchrow(
            """
            INSERT INTO public.record_versions (
                record_id, source_id, org_id, version_index,
                content, content_hash, source_created_at, source_updated_at,
                metadata, is_latest
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, $7, $8,
                $9::jsonb, true
            )
            RETURNING id;
            """,
            record_id,
            source_id,
            org_id,
            next_version_index,
            rec.content,
            content_hash,
            rec.source_created_at,
            rec.source_updated_at,
            json.dumps(rec.metadata),
        )
        version_id = version_row["id"]

        # Generate and insert text chunks
        chunks = chunk_text(rec.content)
        if chunks:
            chunk_records = [
                (
                    version_id,
                    record_id,
                    source_id,
                    org_id,
                    c.chunk_index,
                    c.content,
                    None,  # embedding vector(384) left NULL in Milestone 3A
                    c.token_count,
                )
                for c in chunks
            ]
            await connection.executemany(
                """
                INSERT INTO public.chunks (
                    record_version_id, record_id, source_id, org_id,
                    chunk_index, content, embedding, token_count
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8);
                """,
                chunk_records,
            )

        return True, len(chunks)

    async def _resolve_links(
        self,
        connection: asyncpg.Connection,
        source_id: UUID,
        org_id: UUID,
        pending_links: List[Tuple[UUID, ExtractedLink]],
    ) -> int:
        """
        Resolve pending external links to internal records and persist in public.record_links.
        """
        # Unique target external IDs to lookup
        target_ext_ids = list({link.target_external_id for _, link in pending_links})
        if not target_ext_ids:
            return 0

        target_rows = await connection.fetch(
            """
            SELECT id, external_id
            FROM public.records
            WHERE org_id = $1 AND external_id = ANY($2::text[])
            """,
            org_id,
            target_ext_ids,
        )
        target_map = {r["external_id"]: r["id"] for r in target_rows}

        links_to_insert = []
        for from_rec_id, link in pending_links:
            to_rec_id = target_map.get(link.target_external_id)
            if to_rec_id and to_rec_id != from_rec_id:
                links_to_insert.append((org_id, from_rec_id, to_rec_id, link.link_type, link.provenance))

        if not links_to_insert:
            return 0

        # Insert links idempotently
        await connection.executemany(
            """
            INSERT INTO public.record_links (
                org_id, from_record_id, to_record_id, link_type, provenance
            ) VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (from_record_id, to_record_id, link_type) DO NOTHING;
            """,
            links_to_insert,
        )
        return len(links_to_insert)

    async def _update_source_status(
        self,
        connection: asyncpg.Connection,
        source_id: str,
        org_id: str,
        status: str,
        new_cursor: Dict[str, Any],
        errors: List[str],
    ) -> None:
        """Update sources sync status, cursor, and error details."""
        error_msg = "\n".join(errors) if errors else None
        await connection.execute(
            """
            UPDATE public.sources
            SET sync_status = $3,
                sync_cursor = $4::jsonb,
                last_synced_at = now(),
                error_message = $5,
                updated_at = now()
            WHERE id = $1 AND org_id = $2
            """,
            UUID(source_id),
            UUID(org_id),
            status,
            json.dumps(new_cursor),
            error_msg,
        )

