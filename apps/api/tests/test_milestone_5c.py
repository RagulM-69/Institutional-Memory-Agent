"""
Comprehensive unit and authorization tests for Milestone 5C:
- Knowledge capture & personal notes with source-validated record linking
- Meeting transcript ingestion with pre-computed 384d vector embeddings & atomic rollback
- Handoff containers, item permissions, and confidential evidence redaction
- Answer feedback rating (+1 / -1) and strict ownership verification
"""

from __future__ import annotations

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
)
from apps.api.main import app


# ---------------------------------------------------------------------------
# Test fixtures and mock state
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_context():
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


@pytest.fixture
def other_user():
    return AuthenticatedUser(
        id=uuid4(),
        email="other@acme.corp",
        role="authenticated",
    )


# ---------------------------------------------------------------------------
# 1. Knowledge Notes Tests
# ---------------------------------------------------------------------------

def test_create_knowledge_note_success_without_links(monkeypatch, auth_context):
    user, org = auth_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)

    inserted_note = {}

    class FakeConn:
        async def fetchrow(self, query: str, *args):
            if "INSERT INTO public.knowledge_notes" in query:
                note_id = uuid4()
                inserted_note["id"] = note_id
                inserted_note["org_id"] = args[0]
                inserted_note["author_user_id"] = args[1]
                inserted_note["title"] = args[2]
                inserted_note["content"] = args[3]
                return {
                    "id": note_id,
                    "org_id": args[0],
                    "author_user_id": args[1],
                    "title": args[2],
                    "content": args[3],
                    "status": "personal",
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
            return None

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.knowledge.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.post(
        "/api/knowledge-notes",
        json={"title": "Redis Cache Invalidation Strategy", "content": "We chose a 60-second TTL."},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Redis Cache Invalidation Strategy"
    assert data["status"] == "personal"
    assert data["is_human_contributed"] is True
    assert data["author_user_id"] == str(user.id)
    assert data["linked_records"] == []

    app.dependency_overrides.clear()


def test_create_knowledge_note_rejects_unauthorized_linked_record(monkeypatch, auth_context):
    user, org = auth_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)
    record_id = uuid4()

    class FakeConn:
        async def fetchrow(self, query: str, *args):
            if "public.user_can_access_source" in query:
                # User does NOT have access
                return {
                    "id": record_id,
                    "title": "Confidential Security Audit",
                    "record_type": "security_report",
                    "external_id": "audit:001",
                    "source_id": uuid4(),
                    "has_access": False,
                }
            return None

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.knowledge.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.post(
        "/api/knowledge-notes",
        json={
            "title": "Note with restricted link",
            "content": "Trying to link private audit.",
            "record_ids": [str(record_id)],
        },
    )

    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]

    app.dependency_overrides.clear()


def test_create_knowledge_note_empty_content_returns_400(auth_context):
    user, org = auth_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)

    client = TestClient(app)
    response = client.post(
        "/api/knowledge-notes",
        json={"title": "Valid Title", "content": "   "},
    )

    assert response.status_code == 400
    app.dependency_overrides.clear()


def test_list_knowledge_notes_filters_unauthorized_records(monkeypatch, auth_context):
    user, org = auth_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)

    note_id = uuid4()
    rec_id = uuid4()

    class FakeConn:
        async def fetch(self, query: str, *args):
            if "FROM public.knowledge_notes" in query:
                return [
                    {
                        "id": note_id,
                        "org_id": org.org_id,
                        "author_user_id": user.id,
                        "title": "Architecture Overview",
                        "content": "Service meshes are used everywhere.",
                        "status": "personal",
                        "created_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                    }
                ]
            if "FROM public.knowledge_note_records" in query:
                # Returns only the record caller has permission to view
                return [
                    {
                        "note_id": note_id,
                        "id": rec_id,
                        "title": "Public PR #42",
                        "record_type": "pull_request",
                        "external_id": "pr:42",
                    }
                ]
            return []

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.knowledge.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.get("/api/knowledge-notes")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Architecture Overview"
    assert len(data[0]["linked_records"]) == 1
    assert data[0]["linked_records"][0]["title"] == "Public PR #42"

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 2. Meeting Ingestion & Vector Safety Tests
# ---------------------------------------------------------------------------

def test_meeting_ingestion_success(monkeypatch, auth_context):
    user, org = auth_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)

    # Mock embeddings to return deterministic 384d vectors
    fake_vector = [0.05] * 384
    monkeypatch.setattr("apps.api.routers.meetings.embed_batch", lambda texts: [fake_vector for _ in texts])

    executed_queries: List[str] = []

    class FakeWorkerConn:
        async def fetchrow(self, query: str, *args):
            executed_queries.append(query)
            if "INSERT INTO public.sources" in query:
                return {"id": uuid4()}
            return None

        async def execute(self, query: str, *args):
            executed_queries.append(query)

        async def executemany(self, query: str, args):
            executed_queries.append(query)

        async def fetch(self, query: str, *args):
            executed_queries.append(query)
            return []

    @asynccontextmanager
    async def fake_worker_tx(org_id: UUID):
        yield FakeWorkerConn()

    monkeypatch.setattr("apps.api.routers.meetings.worker_transaction_context", fake_worker_tx)

    client = TestClient(app)
    response = client.post(
        "/api/meetings",
        json={
            "title": "Q3 Platform Architecture Sync",
            "content": "Discussed migrating payment workers to Kafka queues. Ticket PROJ-104 relates to this.",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Q3 Platform Architecture Sync"
    assert data["is_untrusted_evidence"] is True
    assert data["status"] == "indexed"
    assert data["chunk_count"] >= 1

    # Verify atomic queries executed
    assert any("INSERT INTO public.sources" in q for q in executed_queries)
    assert any("INSERT INTO public.records" in q for q in executed_queries)
    assert any("INSERT INTO public.record_versions" in q for q in executed_queries)
    assert any("INSERT INTO public.chunks" in q for q in executed_queries)

    app.dependency_overrides.clear()


def test_meeting_ingestion_fails_before_db_if_embedding_fails(monkeypatch, auth_context):
    user, org = auth_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)

    def failing_embed(texts):
        raise RuntimeError("Embedding model GPU out of memory")

    monkeypatch.setattr("apps.api.routers.meetings.embed_batch", failing_embed)

    db_opened = False

    @asynccontextmanager
    async def fake_worker_tx(org_id: UUID):
        nonlocal db_opened
        db_opened = True
        yield None

    monkeypatch.setattr("apps.api.routers.meetings.worker_transaction_context", fake_worker_tx)

    client = TestClient(app)
    response = client.post(
        "/api/meetings",
        json={
            "title": "Should Fail Early",
            "content": "This content should not reach the database if embeddings cannot be computed.",
        },
    )

    assert response.status_code == 500
    assert "Embedding model error" in response.json()["detail"]
    assert db_opened is False, "DB transaction must not open if embedding fails in memory"

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 3. Handoffs Workspace Tests
# ---------------------------------------------------------------------------

def test_create_handoff_success_with_items(monkeypatch, auth_context):
    user, org = auth_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)

    rec_id = uuid4()

    class FakeConn:
        async def fetchrow(self, query: str, *args):
            if "public.user_can_access_source" in query:
                return {
                    "id": rec_id,
                    "title": "Auth Architecture RFC",
                    "source_id": uuid4(),
                    "has_access": True,
                }
            if "INSERT INTO public.handoffs" in query:
                return {
                    "id": uuid4(),
                    "org_id": org.org_id,
                    "title": args[2],
                    "subject_type": args[3],
                    "subject_identifier": args[4],
                    "status": "draft",
                    "summary": args[5],
                    "departing_user_id": args[6],
                    "recipient_user_id": args[7],
                    "created_by_user_id": user.id,
                    "created_at": datetime.now(timezone.utc),
                }
            return None

        async def execute(self, query: str, *args):
            pass

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.handoffs.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.post(
        "/api/handoffs",
        json={
            "title": "Payments Service Ownership Transfer",
            "subject_type": "service",
            "subject_identifier": "payments-svc",
            "summary": "Transferring maintenance to team B.",
            "items": [
                {
                    "title": "Core RFC Document",
                    "item_status": "verified",
                    "record_id": str(rec_id),
                    "description": "Reviewed and agreed.",
                }
            ],
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Payments Service Ownership Transfer"
    assert data["status"] == "draft"
    assert len(data["items"]) == 1
    assert data["items"][0]["item_status"] == "verified"

    app.dependency_overrides.clear()


def test_create_handoff_rejects_invalid_subject_type(auth_context):
    user, org = auth_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)

    client = TestClient(app)
    response = client.post(
        "/api/handoffs",
        json={
            "title": "Invalid Type Test",
            "subject_type": "cluster",  # Invalid! Must be 'person' or 'service'
            "subject_identifier": "k8s-prod",
        },
    )

    assert response.status_code == 400
    assert "Invalid subject_type" in response.json()["detail"]
    app.dependency_overrides.clear()


def test_get_handoff_redacts_inaccessible_records(monkeypatch, auth_context):
    user, org = auth_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)

    handoff_id = uuid4()
    secret_rec_id = uuid4()

    class FakeConn:
        async def fetchrow(self, query: str, *args):
            if "FROM public.handoffs" in query:
                return {
                    "id": handoff_id,
                    "org_id": org.org_id,
                    "title": "Security Team Handoff",
                    "subject_type": "person",
                    "subject_identifier": "alice@acme.corp",
                    "status": "draft",
                    "summary": "Confidential handoff",
                    "created_by_user_id": user.id,
                    "departing_user_id": None,
                    "recipient_user_id": None,
                    "created_at": datetime.now(timezone.utc),
                }
            return None

        async def fetch(self, query: str, *args):
            if "FROM public.handoff_items" in query:
                return [
                    {
                        "id": uuid4(),
                        "title": "Incident Log 404",
                        "description": "Secret leak details",
                        "item_status": "verified",
                        "record_id": secret_rec_id,
                        "record_title": "Top Secret Incident Log",
                        "record_type": "incident",
                        "source_id": uuid4(),
                        "note_id": None,
                        "note_title": None,
                        "gap_id": None,
                        "user_has_record_access": False,  # Caller does NOT have access!
                    }
                ]
            return []

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.handoffs.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.get(f"/api/handoffs/{handoff_id}")

    assert response.status_code == 200
    data = response.json()
    item = data["items"][0]
    assert item["is_restricted_evidence"] is True
    assert item["record_id"] is None
    assert "[Restricted Evidence]" in item["record_title"]

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 4. Answer Feedback Tests
# ---------------------------------------------------------------------------

def test_submit_feedback_success_by_creator(monkeypatch, auth_context):
    user, org = auth_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)

    answer_id = uuid4()

    class FakeConn:
        async def fetchrow(self, query: str, *args):
            if "FROM public.answers" in query and "SELECT" in query:
                return {"id": answer_id, "created_by_user_id": user.id}
            if "UPDATE public.answers" in query:
                return {
                    "id": answer_id,
                    "feedback_rating": args[0],
                    "feedback_notes": args[1],
                    "created_at": datetime.now(timezone.utc),
                }
            return None

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.feedback.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.post(
        f"/api/answers/{answer_id}/feedback",
        json={"rating": 1, "notes": "Citations were accurate and verified."},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["answer_id"] == str(answer_id)
    assert data["feedback_rating"] == 1
    assert data["feedback_notes"] == "Citations were accurate and verified."

    app.dependency_overrides.clear()


def test_submit_feedback_rejected_for_non_creator(monkeypatch, auth_context, other_user):
    user, org = auth_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)

    answer_id = uuid4()

    class FakeConn:
        async def fetchrow(self, query: str, *args):
            if "FROM public.answers" in query and "SELECT" in query:
                # Created by someone else!
                return {"id": answer_id, "created_by_user_id": other_user.id}
            return None

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.feedback.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.post(
        f"/api/answers/{answer_id}/feedback",
        json={"rating": -1, "notes": "I disagree."},
    )

    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]

    app.dependency_overrides.clear()


def test_submit_feedback_invalid_rating_returns_400(auth_context):
    user, org = auth_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)

    answer_id = uuid4()
    client = TestClient(app)
    response = client.post(
        f"/api/answers/{answer_id}/feedback",
        json={"rating": 5},  # Invalid! Only 1 or -1 allowed
    )

    assert response.status_code == 400
    assert "Feedback rating must be either 1 or -1" in response.json()["detail"]

    app.dependency_overrides.clear()
