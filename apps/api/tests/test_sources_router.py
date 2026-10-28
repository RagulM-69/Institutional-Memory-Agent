"""
Unit and authorization tests for Knowledge Sources Management router:
- Role enforcement: only admins can create, sync, and update sources
- Non-admin members receive HTTP 403 Forbidden for mutation operations
- Server-side credential isolation: raw tokens in config are strictly rejected
- Type-specific configuration validation (GitHub, Jira, Slack)
- Duplicate sync concurrency prevention (HTTP 409 Conflict)
- Soft-archive behavior: keeps historical records and versions intact
- Paginated record inspection under tenant and source isolation
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.auth.dependencies import (
    ActiveOrganization,
    AuthenticatedUser,
    get_organization_context,
    require_admin,
)
from apps.api.connectors.base import FetchResult, ValidationResult
from apps.api.main import app


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_context():
    user = AuthenticatedUser(
        id=uuid4(),
        email="admin@acme.corp",
        role="authenticated",
    )
    org = ActiveOrganization(
        org_id=uuid4(),
        name="Acme Corp",
        slug="acme",
        role="admin",
    )
    return user, org


@pytest.fixture
def member_context():
    user = AuthenticatedUser(
        id=uuid4(),
        email="engineer@acme.corp",
        role="authenticated",
    )
    org = ActiveOrganization(
        org_id=uuid4(),
        name="Acme Corp",
        slug="acme",
        role="member",
    )
    return user, org


@pytest.fixture(autouse=True)
def clean_dependencies():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. Source Creation & Role Enforcement Tests
# ---------------------------------------------------------------------------

def test_admin_can_create_github_source(monkeypatch, admin_context):
    user, org = admin_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)
    app.dependency_overrides[require_admin] = lambda: (user, org)

    source_id = uuid4()
    created_state = {}

    class FakeConn:
        async def execute(self, query: str, *args):
            if "INSERT INTO public.sources" in query:
                created_state["id"] = args[0]
                created_state["org_id"] = args[1]
                created_state["name"] = args[2]
                created_state["type"] = args[3]
                created_state["visibility"] = args[4]
                created_state["config"] = json.loads(args[5])
            return "INSERT 0 1"

        async def fetchrow(self, query: str, *args):
            if "WHERE id = $1 AND org_id = $2" in query:
                return {
                    "id": created_state.get("id", source_id),
                    "org_id": created_state.get("org_id", org.org_id),
                    "name": created_state.get("name", "Core Monorepo"),
                    "type": created_state.get("type", "github"),
                    "visibility": created_state.get("visibility", "public"),
                    "config": json.dumps(created_state.get("config", {"repo": "acme/monorepo"})),
                    "sync_status": "ok",
                    "sync_cursor": {},
                    "last_synced_at": None,
                    "error_message": None,
                    "is_archived": False,
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
            return None

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.sources.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.post(
        "/api/sources",
        json={
            "name": "Core Monorepo",
            "type": "github",
            "visibility": "public",
            "config": {"repo": "acme/monorepo"},
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Core Monorepo"
    assert data["type"] == "github"
    assert data["config"] == {"repo": "acme/monorepo"}
    assert data["sync_status"] == "ok"
    assert data["is_archived"] is False

    app.dependency_overrides.clear()


def test_member_forbidden_from_creating_source(member_context):
    user, org = member_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)
    # Notice: require_admin is NOT overridden with success, it evaluates org.role != admin

    client = TestClient(app)
    response = client.post(
        "/api/sources",
        json={
            "name": "Unauthorized Source",
            "type": "github",
            "config": {"repo": "acme/secret"},
        },
    )

    assert response.status_code == 403
    assert "administrator privileges required" in response.json()["detail"].lower()

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 2. Server-side Credential Protection & Validation
# ---------------------------------------------------------------------------

def test_raw_connector_tokens_rejected_in_config(admin_context):
    user, org = admin_context
    app.dependency_overrides[require_admin] = lambda: (user, org)

    client = TestClient(app)
    # Attempting to supply a raw token in request
    response = client.post(
        "/api/sources",
        json={
            "name": "Leaky Source",
            "type": "github",
            "config": {"repo": "acme/repo", "token": "ghp_supersecret123"},
        },
    )

    assert response.status_code == 400
    assert "forbidden" in response.json()["detail"].lower()
    assert "credentials must be maintained server-side" in response.json()["detail"].lower()

    app.dependency_overrides.clear()


def test_invalid_github_repo_rejected(admin_context):
    user, org = admin_context
    app.dependency_overrides[require_admin] = lambda: (user, org)

    client = TestClient(app)
    response = client.post(
        "/api/sources",
        json={
            "name": "Bad Repo",
            "type": "github",
            "config": {"repo": "invalid-repo-without-slash"},
        },
    )

    assert response.status_code == 400
    assert "owner/repo" in response.json()["detail"].lower()

    app.dependency_overrides.clear()


def test_invalid_jira_base_url_rejected(admin_context):
    user, org = admin_context
    app.dependency_overrides[require_admin] = lambda: (user, org)

    client = TestClient(app)
    response = client.post(
        "/api/sources",
        json={
            "name": "Bad Jira",
            "type": "jira",
            "config": {"base_url": "ftp://jira.corp", "project": "ENG"},
        },
    )

    assert response.status_code == 400
    assert "must begin with http:// or https://" in response.json()["detail"].lower()

    app.dependency_overrides.clear()


def test_invalid_slack_channel_rejected(admin_context):
    user, org = admin_context
    app.dependency_overrides[require_admin] = lambda: (user, org)

    client = TestClient(app)
    response = client.post(
        "/api/sources",
        json={
            "name": "Bad Slack",
            "type": "slack",
            "config": {"channel_id": "bad channel with spaces"},
        },
    )

    assert response.status_code == 400
    assert "channel id" in response.json()["detail"].lower()

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 3. Duplicate Sync Concurrency & Sync Lifecycle Tests
# ---------------------------------------------------------------------------

def test_duplicate_sync_prevention_returns_409(monkeypatch, admin_context):
    user, org = admin_context
    app.dependency_overrides[require_admin] = lambda: (user, org)
    source_id = uuid4()

    class FakeConn:
        async def fetchrow(self, query: str, *args):
            if "FROM public.sources" in query:
                # Source is ALREADY running
                return {
                    "id": source_id,
                    "name": "Already Syncing Source",
                    "type": "github",
                    "sync_status": "running",
                    "is_archived": False,
                }
            return None

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.sources.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.post(f"/api/sources/{source_id}/sync")

    assert response.status_code == 409
    assert "already in progress" in response.json()["detail"].lower()

    app.dependency_overrides.clear()


def test_member_forbidden_from_syncing_source(member_context):
    user, org = member_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)
    source_id = uuid4()

    client = TestClient(app)
    response = client.post(f"/api/sources/{source_id}/sync")

    assert response.status_code == 403
    assert "administrator privileges required" in response.json()["detail"].lower()

    app.dependency_overrides.clear()


def test_sync_source_background_accepted(monkeypatch, admin_context):
    user, org = admin_context
    app.dependency_overrides[require_admin] = lambda: (user, org)
    source_id = uuid4()

    class FakeConn:
        async def fetchrow(self, query: str, *args):
            if "WHERE id = $1 AND org_id = $2" in query:
                return {
                    "id": source_id,
                    "name": "Core Monorepo",
                    "type": "github",
                    "sync_status": "ok",
                    "is_archived": False,
                }
            return None

        async def execute(self, query: str, *args):
            return "UPDATE 1"

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.sources.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.post(f"/api/sources/{source_id}/sync?background=true")

    assert response.status_code == 200
    data = response.json()
    assert data["source_id"] == str(source_id)
    assert data["status"] == "running"
    assert "started in background" in data["message"].lower()

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 4. Soft-Archive & Deletion Protection Tests
# ---------------------------------------------------------------------------

def test_soft_archive_source(monkeypatch, admin_context):
    user, org = admin_context
    app.dependency_overrides[require_admin] = lambda: (user, org)
    source_id = uuid4()

    class FakeConn:
        def __init__(self):
            self.is_archived = False

        async def execute(self, query: str, *args):
            if "UPDATE public.sources" in query:
                self.is_archived = args[3]
            return "UPDATE 1"

        async def fetchrow(self, query: str, *args):
            if "SELECT COUNT(*)" in query:
                return {"count": 12}
            elif "FROM public.sources" in query:
                return {
                    "id": source_id,
                    "org_id": org.org_id,
                    "name": "Obsolete Source",
                    "type": "github",
                    "visibility": "public",
                    "config": "{}",
                    "sync_status": "ok",
                    "sync_cursor": {},
                    "last_synced_at": None,
                    "error_message": None,
                    "is_archived": self.is_archived,
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
            return None

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.sources.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.patch(
        f"/api/sources/{source_id}",
        json={"is_archived": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["is_archived"] is True
    assert data["record_count"] == 12

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 5. Paginated Records Inspection Tests
# ---------------------------------------------------------------------------

def test_list_source_records_paginated(monkeypatch, member_context):
    user, org = member_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)
    source_id = uuid4()
    record_1_id = uuid4()
    version_1_id = uuid4()

    class FakeConn:
        async def fetchrow(self, query: str, *args):
            if "WHERE id = $1 AND org_id = $2" in query:
                return {"id": source_id}
            if "COUNT(*)::int AS total" in query:
                return {"total": 45}
            return None

        async def fetch(self, query: str, *args):
            if "FROM public.records r" in query:
                return [
                    {
                        "id": record_1_id,
                        "org_id": org.org_id,
                        "source_id": source_id,
                        "external_id": "pr:101",
                        "record_type": "pull_request",
                        "created_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                        "current_version_id": version_1_id,
                        "version_index": 2,
                        "title": "Migrate to connection pool",
                        "author_name": "Senior Eng",
                        "url": "https://github.com/acme/monorepo/pull/101",
                        "snippet": "We replaced direct connections with transaction pooler...",
                        "chunk_count": 3,
                    }
                ]
            return []

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.sources.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.get(f"/api/sources/{source_id}/records?limit=10&offset=0")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 45
    assert data["limit"] == 10
    assert data["offset"] == 0
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "Migrate to connection pool"
    assert data["items"][0]["chunk_count"] == 3

    app.dependency_overrides.clear()


def test_list_records_for_nonexistent_source_returns_404(monkeypatch, member_context):
    user, org = member_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)
    source_id = uuid4()

    class FakeConn:
        async def fetchrow(self, query: str, *args):
            return None

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.sources.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.get(f"/api/sources/{source_id}/records")

    assert response.status_code == 404

    app.dependency_overrides.clear()

