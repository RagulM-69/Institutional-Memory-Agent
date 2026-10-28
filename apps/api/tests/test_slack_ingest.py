"""
Comprehensive tests for Slack Web API Connector and Ingestion Pipeline.
Includes mock HTTP transports for Slack Web API, thread/reply handling,
edited/deleted messages, missing fields, cursor pagination, incremental sync,
idempotency, version retirement, and cross-reference extraction.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest

from apps.api.connectors.base import ExtractedLink, FetchResult, NormalizedRecord, ValidationResult
from apps.api.connectors.slack import (
    SlackConnector,
    extract_slack_references,
    slack_ts_to_datetime,
)
from apps.api.ingest.pipeline import IngestPipeline, compute_content_hash


# ─────────────────────────────────────────────────────────────────────────────
# 1. Parsing & Reference Extraction Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_slack_ts_to_datetime():
    dt = slack_ts_to_datetime("1698451200.123456")
    assert dt.tzinfo == timezone.utc
    assert dt.year >= 2023

    # Fallback on invalid
    fallback = slack_ts_to_datetime("invalid")
    assert fallback.tzinfo == timezone.utc


def test_extract_slack_references():
    text = """
    We decided in https://company.slack.com/archives/C0123456789/p1698451200123456 to adopt polling.
    Referenced in Jira PROJ-200 and GitHub PR #42.
    Merged in commit a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0.
    """
    links = extract_slack_references(text)
    targets = {l.target_external_id for l in links}

    assert "slack:C0123456789:1698451200.123456" in targets
    assert "jira:PROJ-200" in targets
    assert "issue:42" in targets
    assert "pr:42" in targets
    assert "commit:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0" in targets

    for l in links:
        assert l.provenance == "slack_reference"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Slack Connector Validation Tests (Mock Transport)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slack_validation_success():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth.test":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "url": "https://team.slack.com/",
                    "team": "Acme Engineering",
                    "user": "handoff_bot",
                    "team_id": "T123",
                    "user_id": "UBOT",
                },
            )
        elif request.url.path == "/api/conversations.info":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "channel": {
                        "id": "C123",
                        "name": "architecture",
                        "is_channel": True,
                        "is_private": False,
                    },
                },
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = SlackConnector(channel_id="C123", token="xoxb-test", client=client)

    result = await connector.validate()
    assert result.is_valid is True
    assert "Acme Engineering" in result.message
    assert "#architecture" in result.message
    assert result.details["channel_name"] == "architecture"


@pytest.mark.asyncio
async def test_slack_validation_invalid_auth():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = SlackConnector(channel_id="C123", token="bad-token", client=client)

    result = await connector.validate()
    assert result.is_valid is False
    assert "invalid_auth" in result.message


@pytest.mark.asyncio
async def test_slack_validation_not_in_channel():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth.test":
            return httpx.Response(200, json={"ok": True, "user": "handoff_bot", "team": "Team"})
        return httpx.Response(200, json={"ok": False, "error": "not_in_channel"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = SlackConnector(channel_id="C123", token="xoxb-test", client=client)

    result = await connector.validate()
    assert result.is_valid is False
    assert "bot is not a member" in result.message


@pytest.mark.asyncio
async def test_slack_validation_missing_scope():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth.test":
            return httpx.Response(200, json={"ok": True, "user": "handoff_bot", "team": "Team"})
        return httpx.Response(200, json={"ok": False, "error": "missing_scope", "needed": "channels:history"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = SlackConnector(channel_id="C123", token="xoxb-test", client=client)

    result = await connector.validate()
    assert result.is_valid is False
    assert "channels:history" in result.message


# ─────────────────────────────────────────────────────────────────────────────
# 3. Slack Connector Fetch Tests (Threads, Replies, Edits, Deletions, Pagination)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slack_fetch_threads_and_replies():
    parent_msg = {
        "type": "message",
        "user": "U_ALICE",
        "text": "Why order-service uses polling instead of webhooks? See PROJ-101.",
        "ts": "1698451200.100000",
        "thread_ts": "1698451200.100000",
        "reply_count": 1,
    }

    reply_msg = {
        "type": "message",
        "user": "U_BOB",
        "text": "Supplier API drops webhooks under load. Documented in PR #42.",
        "ts": "1698452000.200000",
        "thread_ts": "1698451200.100000",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/conversations.info":
            return httpx.Response(200, json={"ok": True, "channel": {"id": "C_ARCH", "name": "arch"}})
        elif path == "/api/conversations.history":
            return httpx.Response(200, json={"ok": True, "messages": [parent_msg], "has_more": False})
        elif path == "/api/conversations.replies":
            return httpx.Response(200, json={"ok": True, "messages": [parent_msg, reply_msg], "has_more": False})
        elif path == "/api/users.info":
            user_id = request.url.params.get("user")
            name = "Alice Lead" if user_id == "U_ALICE" else "Bob Dev"
            email = "alice@example.com" if user_id == "U_ALICE" else "bob@example.com"
            return httpx.Response(
                200,
                json={"ok": True, "user": {"id": user_id, "profile": {"display_name": name, "email": email}}},
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = SlackConnector(channel_id="C_ARCH", token="xoxb-test", client=client)

    result = await connector.fetch()
    assert len(result.records) == 1

    rec = result.records[0]
    assert rec.external_id == "slack:C_ARCH:1698451200.100000"
    assert rec.record_type == "slack_thread"
    assert rec.author_name == "Alice Lead"
    assert rec.author_email == "alice@example.com"
    assert "[#arch]" in rec.title

    # Content includes both initial message and reply
    assert "Why order-service uses polling" in rec.content
    assert "## Replies (1)" in rec.content
    assert "Bob Dev" in rec.content
    assert "Supplier API drops webhooks" in rec.content

    # Extracted links from both parent and reply
    targets = {l.target_external_id for l in rec.extracted_links}
    assert "jira:PROJ-101" in targets
    assert "issue:42" in targets
    assert "pr:42" in targets

    # Cursor captures max timestamp in thread
    assert result.new_cursor.get("latest_ts") == "1698452000.200000"


@pytest.mark.asyncio
async def test_slack_fetch_edited_and_deleted_messages():
    edited_msg = {
        "type": "message",
        "user": "U_ALICE",
        "text": "Updated architectural decision text.",
        "ts": "1698451000.000000",
        "edited": {"user": "U_ALICE", "ts": "1698451500.000000"},
        "reply_count": 0,
    }

    deleted_msg = {
        "type": "message",
        "subtype": "message_deleted",
        "user": "U_ALICE",
        "text": "This message was deleted.",
        "ts": "1698452000.000000",
        "reply_count": 0,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/conversations.info":
            return httpx.Response(200, json={"ok": True, "channel": {"id": "C_1", "name": "general"}})
        elif request.url.path == "/api/conversations.history":
            return httpx.Response(200, json={"ok": True, "messages": [edited_msg, deleted_msg], "has_more": False})
        return httpx.Response(200, json={"ok": True, "user": {"profile": {"display_name": "Alice"}}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = SlackConnector(channel_id="C_1", token="xoxb-test", client=client)

    result = await connector.fetch()
    assert len(result.records) == 2

    rec_edited = result.records[0]
    assert rec_edited.metadata["is_edited"] is True
    assert rec_edited.source_updated_at > rec_edited.source_created_at
    assert rec_edited.is_deleted_upstream is False

    rec_deleted = result.records[1]
    assert rec_deleted.is_deleted_upstream is True


@pytest.mark.asyncio
async def test_slack_fetch_cursor_pagination():
    page1_msgs = [{"type": "message", "text": f"Msg {i}", "ts": f"169845000{i}.000000", "reply_count": 0} for i in range(1, 3)]
    page2_msgs = [{"type": "message", "text": f"Msg {i}", "ts": f"169845000{i}.000000", "reply_count": 0} for i in range(3, 5)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/conversations.info":
            return httpx.Response(200, json={"ok": True, "channel": {"id": "C_PAG", "name": "general"}})
        elif request.url.path == "/api/conversations.history":
            cursor = request.url.params.get("cursor")
            if not cursor:
                return httpx.Response(
                    200,
                    json={"ok": True, "messages": page1_msgs, "has_more": True, "response_metadata": {"next_cursor": "cursor_page_2"}},
                )
            elif cursor == "cursor_page_2":
                return httpx.Response(
                    200,
                    json={"ok": True, "messages": page2_msgs, "has_more": False, "response_metadata": {}},
                )
        return httpx.Response(200, json={"ok": True, "user": {"profile": {"display_name": "User"}}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = SlackConnector(channel_id="C_PAG", token="xoxb-test", client=client)

    # Fetch with limit = 3
    result = await connector.fetch(limit=3)
    assert len(result.records) == 3
    assert result.has_more is True
    assert result.records[0].external_id == "slack:C_PAG:1698450001.000000"
    assert result.records[2].external_id == "slack:C_PAG:1698450003.000000"


@pytest.mark.asyncio
async def test_slack_fetch_rate_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/conversations.info":
            return httpx.Response(200, json={"ok": True, "channel": {"id": "C_1", "name": "dev"}})
        return httpx.Response(429, headers={"Retry-After": "45"}, json={"ok": False, "error": "ratelimited"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = SlackConnector(channel_id="C_1", token="xoxb-test", client=client)

    result = await connector.fetch()
    assert len(result.errors) > 0
    assert any("rate limit exceeded" in e for e in result.errors)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Ingest Pipeline Idempotency & Versioning with Slack Records (Mock DB)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_slack_idempotency_and_versioning():
    """
    Verify Slack threads are ingested as record_type='slack_thread',
    re-sync is idempotent, and new replies/edits create version 2.
    """
    pipeline = IngestPipeline()
    mock_conn = AsyncMock()
    org_id = uuid4()
    source_id = uuid4()
    record_id = uuid4()

    mock_conn.fetchrow.side_effect = [
        # Source lookup
        {
            "id": source_id,
            "name": "Slack Source",
            "type": "slack",
            "config": json.dumps({"channel_id": "C_ARCH"}),
            "sync_cursor": json.dumps({}),
            "sync_status": "ok",
        },
        # Upsert record
        {"id": record_id, "is_new": True},
        # Existing version: none
        None,
        # Insert version 1
        {"id": uuid4()},
    ]

    slack_rec = NormalizedRecord(
        external_id="slack:C_ARCH:1698451200.100000",
        record_type="slack_thread",
        title="[#arch] Initial Thread",
        content="# Slack Thread in #arch\nInitial message content.",
        source_created_at=datetime.now(timezone.utc),
        source_updated_at=datetime.now(timezone.utc),
    )

    mock_connector = AsyncMock()
    mock_connector.fetch.return_value = FetchResult(
        records=[slack_rec],
        new_cursor={"latest_ts": "1698451200.100000"},
        has_more=False,
        errors=[],
    )

    report = await pipeline.sync_source(
        source_id=source_id,
        org_id=org_id,
        connector=mock_connector,
        connection=mock_conn,
    )

    assert report.status == "ok"
    assert report.records_scanned == 1
    assert report.records_created == 1
    assert report.versions_created == 1
    assert report.chunks_created >= 1

    # Second run: identical content skips version insertion (idempotent)
    content_hash = compute_content_hash(slack_rec.content)
    mock_conn.fetchrow.side_effect = [
        {
            "id": source_id,
            "name": "Slack Source",
            "type": "slack",
            "config": json.dumps({"channel_id": "C_ARCH"}),
            "sync_cursor": json.dumps({}),
            "sync_status": "ok",
        },
        {"id": record_id, "is_new": False},
        {"id": uuid4(), "version_index": 1, "content_hash": content_hash},
    ]

    report2 = await pipeline.sync_source(
        source_id=source_id,
        org_id=org_id,
        connector=mock_connector,
        connection=mock_conn,
    )

    assert report2.records_updated == 1
    assert report2.versions_created == 0
    assert report2.chunks_created == 0

    # Third run: reply added to thread -> content hash changes -> version 2 created!
    updated_rec = NormalizedRecord(
        external_id="slack:C_ARCH:1698451200.100000",
        record_type="slack_thread",
        title="[#arch] Initial Thread",
        content="# Slack Thread in #arch\nInitial message content.\n\n## Replies (1)\n### Reply by Bob: Agreed on polling.",
        source_created_at=datetime.now(timezone.utc),
        source_updated_at=datetime.now(timezone.utc),
    )
    mock_connector.fetch.return_value = FetchResult(
        records=[updated_rec],
        new_cursor={"latest_ts": "1698453000.000000"},
        has_more=False,
        errors=[],
    )

    mock_conn.fetchrow.side_effect = [
        {
            "id": source_id,
            "name": "Slack Source",
            "type": "slack",
            "config": json.dumps({"channel_id": "C_ARCH"}),
            "sync_cursor": json.dumps({}),
            "sync_status": "ok",
        },
        {"id": record_id, "is_new": False},
        # Version 1 exists with old content hash
        {"id": uuid4(), "version_index": 1, "content_hash": content_hash},
        # Version 2 inserted
        {"id": uuid4()},
    ]

    report3 = await pipeline.sync_source(
        source_id=source_id,
        org_id=org_id,
        connector=mock_connector,
        connection=mock_conn,
    )

    assert report3.records_updated == 1
    assert report3.versions_created == 1
    assert report3.chunks_created >= 1

