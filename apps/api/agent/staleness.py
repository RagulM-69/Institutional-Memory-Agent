"""
Staleness detection for retrieved evidence and cited claims.
Analyzes whether cited record versions have newer revisions or updates,
providing plain-language warnings without declaring older records invalid.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Set
from uuid import UUID

import asyncpg

from apps.api.retrieval.search import EvidenceChunk

logger = logging.getLogger(__name__)


async def check_evidence_staleness(
    chunks: List[EvidenceChunk],
    connection: Optional[asyncpg.Connection] = None,
) -> Optional[str]:
    """
    Check if any cited evidence chunks refer to superseded record versions
    or records with subsequent updates.

    Returns a plain-language warning string if staleness is detected, or None.
    Never asserts that older records are invalid—only highlights newer context.
    """
    if not chunks:
        return None

    # Group cited chunks by record_id
    cited_records: Dict[str, Dict[str, any]] = {}
    for chunk in chunks:
        r_id = str(chunk.record_id)
        if r_id not in cited_records:
            cited_records[r_id] = {
                "title": chunk.record_title,
                "versions": set(),
                "latest_cited_version": chunk.version_index,
                "latest_cited_updated_at": chunk.source_updated_at,
            }
        cited_records[r_id]["versions"].add(chunk.version_index)
        if chunk.version_index > cited_records[r_id]["latest_cited_version"]:
            cited_records[r_id]["latest_cited_version"] = chunk.version_index
            cited_records[r_id]["latest_cited_updated_at"] = chunk.source_updated_at

    warnings: List[str] = []

    # If connection is available, query live database for latest version info
    if connection is not None:
        try:
            record_uuids = [UUID(rid) for rid in cited_records.keys()]
            query = """
                SELECT 
                    r.id as record_id,
                    r.title,
                    rv.id as latest_version_id,
                    rv.version_index as latest_version_index,
                    rv.source_updated_at as latest_updated_at
                FROM public.record_versions rv
                JOIN public.records r ON r.id = rv.record_id
                WHERE rv.is_latest = true
                  AND rv.record_id = ANY($1::uuid[])
            """
            rows = await connection.fetch(query, record_uuids)
            for row in rows:
                rid = str(row["record_id"])
                if rid in cited_records:
                    info = cited_records[rid]
                    latest_v = row["latest_version_index"]
                    cited_v = info["latest_cited_version"]
                    if latest_v > cited_v:
                        updated_str = row["latest_updated_at"].strftime("%Y-%m-%d") if row["latest_updated_at"] else "a later date"
                        warnings.append(
                            f"Record '{row['title']}' has newer revisions available (cited version: v{cited_v}, "
                            f"latest: v{latest_v} updated {updated_str}). Content may have evolved since this decision."
                        )
        except Exception as e:
            logger.warning("Failed to query live database for staleness: %s", e)

    # Fallback or additional static check across retrieved chunks
    # (e.g. if retrieval set contains multiple versions of the same record)
    for rid, info in cited_records.items():
        if len(info["versions"]) > 1:
            versions_sorted = sorted(list(info["versions"]))
            min_v, max_v = versions_sorted[0], versions_sorted[-1]
            if min_v < max_v and not any(info["title"] in w for w in warnings):
                warnings.append(
                    f"Record '{info['title']}' has multiple versions in retrieved evidence "
                    f"(v{min_v} to v{max_v}). Answers may reflect historical context that was modified in later revisions."
                )

    if warnings:
        return " | ".join(warnings)
    return None

