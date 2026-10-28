"""
Comprehensive tests for Jira Cloud Connector and Ingestion Pipeline.
Includes mock HTTP transports for Jira Cloud REST API, ADF parsing,
comments handling, missing fields, pagination, incremental sync,
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
from apps.api.connectors.jira import JiraConnector, adf_to_text
from apps.api.ingest.pipeline import IngestPipeline, compute_content_hash


# ─────────────────────────────────────────────────────────────────────────────
# 1. ADF (Atlassian Document Format) Parsing Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_adf_to_text_plain_string_and_none():
    assert adf_to_text("Plain text description") == "Plain text description"
    assert adf_to_text("") == ""
    assert adf_to_text(None) == ""


def test_adf_to_text_complex_structure():
    adf = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": "Architecture Decision"}],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "We are replacing polling with webhooks as discussed in "},
                    {
                        "type": "text",
                        "text": "PR #42",
                        "marks": [{"type": "link", "attrs": {"href": "https://github.com/org/repo/pull/42"}}],
                    },
                    {"type": "text", "text": "."},
                ],
            },
            {
                "type": "codeBlock",
                "attrs": {"language": "python"},
                "content": [{"type": "text", "text": "def handle_webhook():\n    pass"}],
            },
            {
                "type": "bulletList",
                "content": [
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Low latency"}]}]},
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Reduced load"}]}]},
                ],
            },
            {
                "type": "blockquote",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Approved by security team."}]}],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "mention", "attrs": {"text": "Alice"}},
                    {"type": "text", "text": "to verify rollback steps."},
                ],
            },
        ],
    }

    parsed = adf_to_text(adf)
    assert "# Architecture Decision" in parsed
    assert "[PR #42](https://github.com/org/repo/pull/42)" in parsed
    assert "```python\ndef handle_webhook():\n    pass\n```" in parsed
    assert "- Low latency" in parsed
    assert "> Approved by security team." in parsed
    assert "@Alice to verify rollback steps." in parsed


# ─────────────────────────────────────────────────────────────────────────────
# 2. Jira Connector Validation Tests (Mock Transport)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_jira_validation_success_with_project():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/myself":
            return httpx.Response(
                200,
                json={
                    "displayName": "Alice Engineer",
                    "emailAddress": "alice@example.com",
                    "active": True,
                },
            )
        elif request.url.path == "/rest/api/3/project/PROJ":
            return httpx.Response(
                200,
                json={
                    "key": "PROJ",
                    "name": "Order Management System",
                },
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = JiraConnector(
        base_url="https://example.atlassian.net",
        email="alice@example.com",
        token="secret-token",
        project="PROJ",
        client=client,
    )

    result = await connector.validate()
    assert result.is_valid is True
    assert "Connected to Jira as Alice Engineer" in result.message
    assert result.details["project_key"] == "PROJ"
    assert result.details["project_name"] == "Order Management System"


@pytest.mark.asyncio
async def test_jira_validation_401_unauthorized():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthorized"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = JiraConnector(
        base_url="https://example.atlassian.net",
        email="bad@example.com",
        token="bad-token",
        client=client,
    )

    result = await connector.validate()
    assert result.is_valid is False
    assert result.details["status_code"] == 401
    assert "authentication failed" in result.message.lower()


@pytest.mark.asyncio
async def test_jira_validation_404_project_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/myself":
            return httpx.Response(200, json={"displayName": "Bob"})
        return httpx.Response(404, json={"message": "Project not found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = JiraConnector(
        base_url="https://example.atlassian.net",
        email="bob@example.com",
        token="token",
        project="NONEXISTENT",
        client=client,
    )

    result = await connector.validate()
    assert result.is_valid is False
    assert result.details["status_code"] == 404
    assert "not found" in result.message.lower()


@pytest.mark.asyncio
async def test_jira_validation_429_rate_limited():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "60"}, json={"message": "Rate limited"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = JiraConnector(
        base_url="https://example.atlassian.net",
        email="bob@example.com",
        token="token",
        client=client,
    )

    result = await connector.validate()
    assert result.is_valid is False
    assert result.details.get("rate_limited") is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. Jira Connector Fetch Tests (Pagination, Missing Fields, Comments, Links)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_jira_fetch_issues_and_comments():
    sample_issue = {
        "id": "10001",
        "key": "PROJ-101",
        "fields": {
            "summary": "Implement order polling fallback",
            "description": "See PR #42 and commit 7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b. Related to ENG-50.",
            "status": {"name": "In Progress"},
            "issuetype": {"name": "Task"},
            "project": {"key": "PROJ", "name": "Order Service"},
            "reporter": {"displayName": "Alice Lead", "emailAddress": "alice@example.com"},
            "assignee": {"displayName": "Bob Dev", "emailAddress": "bob@example.com"},
            "labels": ["payments", "backend"],
            "priority": {"name": "High"},
            "created": "2026-10-01T09:00:00.000+0000",
            "updated": "2026-10-02T15:00:00.000+0000",
            "comment": {
                "total": 1,
                "comments": [
                    {
                        "id": "20001",
                        "author": {"displayName": "Bob Dev"},
                        "body": "Benchmarks show polling handles 500 req/s safely. Resolves #42.",
                        "created": "2026-10-02T14:00:00.000+0000",
                        "updated": "2026-10-02T14:30:00.000+0000",
                    }
                ],
            },
            "issuelinks": [
                {
                    "type": {"name": "Blocks", "outward": "blocks"},
                    "outwardIssue": {"key": "PROJ-102"},
                }
            ],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/rest/api/3/search" in request.url.path
        return httpx.Response(
            200,
            json={
                "startAt": 0,
                "maxResults": 50,
                "total": 1,
                "issues": [sample_issue],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = JiraConnector(
        base_url="https://example.atlassian.net",
        email="test@example.com",
        token="token",
        project="PROJ",
        client=client,
    )

    result = await connector.fetch()
    assert len(result.records) == 1

    record = result.records[0]
    assert record.external_id == "jira:PROJ-101"
    assert record.record_type == "ticket"
    assert record.title == "[PROJ-101] Implement order polling fallback"
    assert record.author_name == "Alice Lead"
    assert record.author_email == "alice@example.com"
    assert "https://example.atlassian.net/browse/PROJ-101" == record.url

    # Check content body and comments inclusion
    assert "# [PROJ-101] Implement order polling fallback" in record.content
    assert "High" in record.content
    assert "Bob Dev" in record.content
    assert "## Comments" in record.content
    assert "Benchmarks show polling handles 500 req/s" in record.content

    # Check extracted links
    targets = {l.target_external_id for l in record.extracted_links}
    assert "issue:42" in targets
    assert "pr:42" in targets
    assert "jira:ENG-50" in targets
    assert "jira:PROJ-102" in targets  # from issuelinks
    assert "commit:7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b" in targets

    # Cursor should capture updated timestamp
    assert result.new_cursor.get("since") == "2026-10-02T15:00:00.000+0000"


@pytest.mark.asyncio
async def test_jira_fetch_missing_optional_fields():
    """Test graceful handling of tickets with null/missing description, assignee, priority, labels, comments."""
    minimal_issue = {
        "id": "10002",
        "key": "MIN-1",
        "fields": {
            "summary": "Minimal Ticket",
            "description": None,
            "status": None,
            "issuetype": None,
            "project": None,
            "reporter": None,
            "assignee": None,
            "labels": [],
            "priority": None,
            "created": "2026-10-01T10:00:00.000+0000",
            "updated": "2026-10-01T10:00:00.000+0000",
            "comment": None,
            "issuelinks": [],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "startAt": 0,
                "maxResults": 50,
                "total": 1,
                "issues": [minimal_issue],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = JiraConnector(
        base_url="https://example.atlassian.net",
        email="test@example.com",
        token="token",
        client=client,
    )

    result = await connector.fetch()
    assert len(result.records) == 1
    rec = result.records[0]
    assert rec.external_id == "jira:MIN-1"
    assert rec.author_name is None
    assert rec.author_email is None
    assert "No description provided." in rec.content
    assert rec.metadata["assignee"] is None
    assert rec.metadata["comments_count"] == 0


@pytest.mark.asyncio
async def test_jira_fetch_pagination():
    """Verify pagination across multiple pages with limit handling."""
    def handler(request: httpx.Request) -> httpx.Response:
        start_at = int(request.url.params.get("startAt", 0))
        max_results = int(request.url.params.get("maxResults", 2))

        all_issues = [
            {"id": "1", "key": f"PAGE-{i}", "fields": {"summary": f"Summary {i}", "created": "2026-10-01T00:00:00.000Z", "updated": f"2026-10-0{i}T00:00:00.000Z"}}
            for i in range(1, 6)
        ]
        page = all_issues[start_at : start_at + max_results]

        return httpx.Response(
            200,
            json={
                "startAt": start_at,
                "maxResults": max_results,
                "total": 5,
                "issues": page,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = JiraConnector(
        base_url="https://example.atlassian.net",
        email="test@example.com",
        token="token",
        client=client,
    )

    # Fetch with limit = 3
    result = await connector.fetch(limit=3)
    assert len(result.records) == 3
    assert result.has_more is True
    assert result.records[0].external_id == "jira:PAGE-1"
    assert result.records[2].external_id == "jira:PAGE-3"


@pytest.mark.asyncio
async def test_jira_fetch_incremental_cursor():
    """Verify cursor since timestamp is formatted in JQL and updated properly."""
    called_jql = []

    def handler(request: httpx.Request) -> httpx.Response:
        called_jql.append(request.url.params.get("jql", ""))
        return httpx.Response(
            200,
            json={
                "startAt": 0,
                "maxResults": 50,
                "total": 1,
                "issues": [
                    {
                        "id": "1",
                        "key": "INC-1",
                        "fields": {
                            "summary": "Incremental Ticket",
                            "created": "2026-10-01T00:00:00.000Z",
                            "updated": "2026-10-05T12:00:00.000Z",
                        },
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = JiraConnector(
        base_url="https://example.atlassian.net",
        email="test@example.com",
        token="token",
        project="INC",
        client=client,
    )

    result = await connector.fetch(cursor={"since": "2026-10-04T10:00:00Z"})
    assert len(called_jql) == 1
    # JQL should filter by updated >= "2026-10-04 10:00"
    assert 'updated >= "2026-10-04 10:00"' in called_jql[0]
    assert 'project = "INC"' in called_jql[0]
    assert result.new_cursor.get("since") == "2026-10-05T12:00:00.000Z"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Pipeline Idempotency & Versioning with Jira Records (Mock DB)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_jira_idempotency_and_versioning():
    """
    Test that Jira tickets are ingested as record_type='ticket',
    re-sync is idempotent when unchanged, and content update produces version 2.
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
            "name": "Jira Source",
            "type": "jira",
            "config": json.dumps({"base_url": "https://example.atlassian.net", "project": "PROJ"}),
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

    jira_rec = NormalizedRecord(
        external_id="jira:PROJ-1",
        record_type="ticket",
        title="[PROJ-1] Initial Summary",
        content="# [PROJ-1] Initial Summary\nDescription: Polling design.",
        source_created_at=datetime.now(timezone.utc),
        source_updated_at=datetime.now(timezone.utc),
    )

    mock_connector = AsyncMock()
    mock_connector.fetch.return_value = FetchResult(
        records=[jira_rec],
        new_cursor={"since": "2026-10-05T12:00:00Z"},
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

    # Second run: identical content skips version insertion
    content_hash = compute_content_hash(jira_rec.content)
    mock_conn.fetchrow.side_effect = [
        {
            "id": source_id,
            "name": "Jira Source",
            "type": "jira",
            "config": json.dumps({"base_url": "https://example.atlassian.net"}),
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

    # Third run: comment added to Jira issue -> content changed -> version 2 created!
    updated_rec = NormalizedRecord(
        external_id="jira:PROJ-1",
        record_type="ticket",
        title="[PROJ-1] Initial Summary",
        content="# [PROJ-1] Initial Summary\nDescription: Polling design.\n\n## Comments\n### Comment by Bob: Updated with benchmarks.",
        source_created_at=datetime.now(timezone.utc),
        source_updated_at=datetime.now(timezone.utc),
    )
    mock_connector.fetch.return_value = FetchResult(
        records=[updated_rec],
        new_cursor={"since": "2026-10-06T12:00:00Z"},
        has_more=False,
        errors=[],
    )

    mock_conn.fetchrow.side_effect = [
        {
            "id": source_id,
            "name": "Jira Source",
            "type": "jira",
            "config": json.dumps({"base_url": "https://example.atlassian.net"}),
            "sync_cursor": json.dumps({}),
            "sync_status": "ok",
        },
        {"id": record_id, "is_new": False},
        # Existing version 1 has OLD content hash
        {"id": uuid4(), "version_index": 1, "content_hash": content_hash},
        # Insert version 2
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

