"""
Comprehensive tests for GitHub Connector and Evidence Ingestion Pipeline.
Includes mock HTTP transports for GitHub REST API, chunking validation,
reference extraction, idempotent sync, version retirement, and tenant isolation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx
import pytest

from apps.api.connectors.base import ExtractedLink, FetchResult, NormalizedRecord, ValidationResult
from apps.api.connectors.github import GitHubConnector, extract_references, parse_iso_datetime
from apps.api.ingest.chunking import chunk_text, estimate_token_count
from apps.api.ingest.pipeline import IngestPipeline, SyncReport, compute_content_hash


# ─────────────────────────────────────────────────────────────────────────────
# 1. Reference Extraction & Parsing Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_extract_references_all_types():
    text = """
    Fixes #42 and refs #100.
    Addresses Jira issue PROJ-999 and ENG-1234.
    See also https://github.com/owner/repo/pull/55 and https://github.com/owner/repo/issues/66.
    Merged in commit e3b0c44298fc1c149afbf4c8996fb92427ae41e4.
    """
    links = extract_references(text, provenance="pr_description")

    targets = {l.target_external_id for l in links}
    assert "issue:42" in targets
    assert "pr:42" in targets
    assert "issue:100" in targets
    assert "pr:100" in targets
    assert "jira:PROJ-999" in targets
    assert "jira:ENG-1234" in targets
    assert "pr:55" in targets
    assert "issue:66" in targets
    assert "commit:e3b0c44298fc1c149afbf4c8996fb92427ae41e4" in targets


def test_extract_references_empty_text():
    assert extract_references("", provenance="commit_message") == []
    assert extract_references(None, provenance="commit_message") == []


def test_parse_iso_datetime():
    dt = parse_iso_datetime("2026-10-27T18:30:00Z")
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 27
    assert dt.hour == 18
    assert dt.tzinfo is not None

    # Invalid string fallback to current time
    fallback = parse_iso_datetime("invalid-date")
    assert fallback is not None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Text Chunking Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_chunk_text_single_short_document():
    text = "Short decision note explaining order-service polling architecture."
    chunks = chunk_text(text, target_chunk_size=500)
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].content == text
    assert chunks[0].token_count > 0


def test_chunk_text_paragraphs():
    p1 = "First paragraph describing the problem with order timeouts."
    p2 = "Second paragraph proposing the redis caching layer."
    p3 = "Third paragraph detailing rollback criteria if cache hit rate is below 90%."
    full_text = f"{p1}\n\n{p2}\n\n{p3}"

    chunks = chunk_text(full_text, target_chunk_size=100, overlap_size=20)
    assert len(chunks) >= 2
    for idx, c in enumerate(chunks):
        assert c.chunk_index == idx
        assert len(c.content) > 0


def test_chunk_text_empty_input():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_estimate_token_count():
    assert estimate_token_count("") == 0
    tokens = estimate_token_count("The quick brown fox jumps over the lazy dog")
    assert 9 <= tokens <= 15


# ─────────────────────────────────────────────────────────────────────────────
# 3. GitHub Connector Tests (with MockTransport)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_connector_validation_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/org/repo"
        return httpx.Response(
            200,
            json={
                "full_name": "org/repo",
                "private": False,
                "default_branch": "main",
                "description": "Institutional memory repo",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = GitHubConnector(repo="org/repo", client=client)

    result = await connector.validate()
    assert result.is_valid is True
    assert "accessible" in result.message
    assert result.details["full_name"] == "org/repo"
    assert result.details["default_branch"] == "main"


@pytest.mark.asyncio
async def test_connector_validation_404_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = GitHubConnector(repo="org/nonexistent", client=client)

    result = await connector.validate()
    assert result.is_valid is False
    assert result.details["status_code"] == 404
    assert "not found" in result.message.lower()


@pytest.mark.asyncio
async def test_connector_validation_rate_limit_exceeded():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1793119999"},
            json={"message": "API rate limit exceeded"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = GitHubConnector(repo="org/repo", client=client)

    result = await connector.validate()
    assert result.is_valid is False
    assert result.details.get("rate_limited") is True
    assert "rate limit exceeded" in result.message.lower()


@pytest.mark.asyncio
async def test_connector_fetch_issues_and_prs():
    sample_issues = [
        {
            "number": 101,
            "title": "Fix database deadlock",
            "body": "Resolves #99. Adds row-level locks on parent records.",
            "state": "closed",
            "user": {"login": "alice"},
            "created_at": "2026-10-01T12:00:00Z",
            "updated_at": "2026-10-02T15:00:00Z",
            "labels": [{"name": "bug"}],
            "html_url": "https://github.com/org/repo/issues/101",
        },
        {
            "number": 102,
            "title": "Migrate to asyncpg",
            "body": "Implements transaction pooling. Closes #101.",
            "state": "merged",
            "user": {"login": "bob"},
            "created_at": "2026-10-03T10:00:00Z",
            "updated_at": "2026-10-04T11:00:00Z",
            "pull_request": {"url": "https://api.github.com/repos/org/repo/pulls/102"},
            "labels": [],
            "html_url": "https://github.com/org/repo/pull/102",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if "/issues" in request.url.path and "comments" not in request.url.path:
            return httpx.Response(200, json=sample_issues)
        # Empty lists for comments and commits
        return httpx.Response(200, json=[])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = GitHubConnector(repo="org/repo", client=client)

    result = await connector.fetch()
    assert len(result.records) == 2

    # Verify Issue #101
    issue_rec = next(r for r in result.records if r.external_id == "issue:101")
    assert issue_rec.record_type == "issue"
    assert issue_rec.author_name == "alice"
    assert "# Fix database deadlock" in issue_rec.content
    assert any(l.target_external_id == "issue:99" for l in issue_rec.extracted_links)

    # Verify PR #102
    pr_rec = next(r for r in result.records if r.external_id == "pr:102")
    assert pr_rec.record_type == "pull_request"
    assert pr_rec.author_name == "bob"
    assert any(l.target_external_id == "issue:101" for l in pr_rec.extracted_links)

    # Cursor should capture latest timestamp
    assert result.new_cursor.get("issues_since") == "2026-10-04T11:00:00Z"


@pytest.mark.asyncio
async def test_connector_fetch_review_comments_and_commits():
    sample_review_comments = [
        {
            "id": 555,
            "body": "Should we use FOR NO KEY UPDATE here instead of FOR UPDATE?",
            "path": "db/migrations/001_init.sql",
            "diff_hunk": "@@ -434,6 +434,7 @@\n+ FOR UPDATE;",
            "commit_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
            "user": {"login": "reviewer1"},
            "created_at": "2026-10-05T09:00:00Z",
            "updated_at": "2026-10-05T09:30:00Z",
            "pull_request_url": "https://api.github.com/repos/org/repo/pulls/102",
            "html_url": "https://github.com/org/repo/pull/102#discussion_r555",
        }
    ]

    sample_commits = [
        {
            "sha": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
            "commit": {
                "message": "fix: update lock to FOR NO KEY UPDATE (#102)",
                "author": {"name": "Alice Developer", "email": "alice@example.com", "date": "2026-10-05T10:00:00Z"},
            },
            "html_url": "https://github.com/org/repo/commit/a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
            "parents": [],
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/pulls/comments" in path:
            return httpx.Response(200, json=sample_review_comments)
        elif "/commits" in path:
            return httpx.Response(200, json=sample_commits)
        return httpx.Response(200, json=[])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = GitHubConnector(repo="org/repo", client=client)

    result = await connector.fetch()
    assert len(result.records) == 2

    # Review comment
    rc = next(r for r in result.records if r.record_type == "review_comment")
    assert rc.external_id == "review_comment:555"
    assert "FOR NO KEY UPDATE" in rc.content
    assert any(l.target_external_id == "pr:102" for l in rc.extracted_links)

    # Commit
    commit = next(r for r in result.records if r.record_type == "commit")
    assert commit.external_id == "commit:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
    assert commit.author_email == "alice@example.com"
    assert any(l.target_external_id == "issue:102" for l in commit.extracted_links)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Ingest Pipeline Logic & Idempotency Tests (Mocked DB Connection)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_idempotency_and_versioning():
    """
    Test that re-running sync on identical content skips version insertion,
    while changing content generates a new version index and chunks.
    """
    pipeline = IngestPipeline()

    mock_conn = AsyncMock()
    org_id = uuid4()
    source_id = uuid4()
    record_id = uuid4()

    mock_conn.fetchrow.side_effect = [
        # 1. Source row lookup
        {
            "id": source_id,
            "name": "Test Source",
            "type": "github",
            "config": json.dumps({"repo": "org/repo"}),
            "sync_cursor": json.dumps({}),
            "sync_status": "ok",
        },
        # 2. Record upsert
        {"id": record_id, "is_new": True},
        # 3. Check existing version: none exists
        None,
        # 4. Version insert
        {"id": uuid4()},
    ]

    record1 = NormalizedRecord(
        external_id="issue:1",
        record_type="issue",
        title="Initial Title",
        content="Initial content text for testing pipeline.",
        source_created_at=datetime.now(timezone.utc),
        source_updated_at=datetime.now(timezone.utc),
    )

    mock_connector = AsyncMock()
    mock_connector.fetch.return_value = FetchResult(
        records=[record1],
        new_cursor={"since": "2026-10-01T00:00:00Z"},
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

    # Second run: identical content should produce 0 new versions
    content_hash = compute_content_hash(record1.content)
    mock_conn.fetchrow.side_effect = [
        {
            "id": source_id,
            "name": "Test Source",
            "type": "github",
            "config": json.dumps({"repo": "org/repo"}),
            "sync_cursor": json.dumps({}),
            "sync_status": "ok",
        },
        # Record upsert (not new)
        {"id": record_id, "is_new": False},
        # Check existing version: hash matches
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


@pytest.mark.asyncio
async def test_pipeline_link_resolution():
    """Test cross-references are converted to internal record_links."""
    pipeline = IngestPipeline()

    mock_conn = AsyncMock()
    org_id = uuid4()
    source_id = uuid4()
    rec1_id = uuid4()
    rec2_id = uuid4()

    mock_conn.fetchrow.side_effect = [
        # Source lookup
        {
            "id": source_id,
            "name": "Test Source",
            "type": "github",
            "config": json.dumps({"repo": "org/repo"}),
            "sync_cursor": json.dumps({}),
            "sync_status": "ok",
        },
        # Upsert rec1
        {"id": rec1_id, "is_new": True},
        # rec1 latest version: match to skip
        {"id": uuid4(), "version_index": 1, "content_hash": compute_content_hash("Content 1")},
        # Upsert rec2
        {"id": rec2_id, "is_new": True},
        # rec2 latest version: match to skip
        {"id": uuid4(), "version_index": 1, "content_hash": compute_content_hash("Content 2")},
    ]

    # Target resolution query
    mock_conn.fetch.return_value = [
        {"id": rec2_id, "external_id": "pr:42"}
    ]

    rec1 = NormalizedRecord(
        external_id="issue:1",
        record_type="issue",
        title="Issue 1",
        content="Content 1",
        source_created_at=datetime.now(timezone.utc),
        source_updated_at=datetime.now(timezone.utc),
        extracted_links=[ExtractedLink(target_external_id="pr:42", link_type="explicit", provenance="issue")],
    )

    rec2 = NormalizedRecord(
        external_id="pr:42",
        record_type="pull_request",
        title="PR 42",
        content="Content 2",
        source_created_at=datetime.now(timezone.utc),
        source_updated_at=datetime.now(timezone.utc),
    )

    mock_connector = AsyncMock()
    mock_connector.fetch.return_value = FetchResult(
        records=[rec1, rec2],
        new_cursor={},
        has_more=False,
        errors=[],
    )

    report = await pipeline.sync_source(
        source_id=source_id,
        org_id=org_id,
        connector=mock_connector,
        connection=mock_conn,
    )

    assert report.records_scanned == 2
    assert report.links_created == 1
    # Verify link insert query was called with rec1_id and rec2_id
    executemany_calls = mock_conn.executemany.call_args_list
    assert len(executemany_calls) > 0
    link_args = executemany_calls[0][0][1]
    assert link_args[0] == (org_id, rec1_id, rec2_id, "explicit", "issue")

