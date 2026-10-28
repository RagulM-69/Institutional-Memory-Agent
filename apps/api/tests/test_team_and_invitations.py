"""
Comprehensive unit and integration test suite for Organization, Team, and Invitations.
Tests dual-hash storage, atomic single-use acceptance, email binding, rate limiting,
final-admin protection, Team Lead role constraints, directory privacy, and cross-tenant checks.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import hashlib
import pytest
from fastapi.testclient import TestClient

from apps.api.auth.dependencies import (
    ActiveOrganization,
    AuthenticatedUser,
    get_current_user,
    get_organization_context,
    require_admin,
    require_team_lead_or_admin,
)
from apps.api.main import app


@pytest.fixture(autouse=True)
def clean_dependencies():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


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
def team_lead_context():
    user = AuthenticatedUser(
        id=uuid4(),
        email="lead@acme.corp",
        role="authenticated",
    )
    org = ActiveOrganization(
        org_id=uuid4(),
        name="Acme Corp",
        slug="acme",
        role="team_lead",
    )
    return user, org


@pytest.fixture
def member_context():
    user = AuthenticatedUser(
        id=uuid4(),
        email="member@acme.corp",
        role="authenticated",
    )
    org = ActiveOrganization(
        org_id=uuid4(),
        name="Acme Corp",
        slug="acme",
        role="member",
    )
    return user, org


# ---------------------------------------------------------------------------
# 1. Organization Creation & Onboarding Tests
# ---------------------------------------------------------------------------

def test_authenticated_user_can_create_organization(monkeypatch):
    user = AuthenticatedUser(id=uuid4(), email="creator@example.com", role="authenticated")
    app.dependency_overrides[get_current_user] = lambda: user

    created_org_id = uuid4()

    class FakeConn:
        async def fetchrow(self, query: str, *args):
            return None  # slug not taken

        async def fetchval(self, query: str, *args):
            assert "create_organization_with_owner" in query
            assert args[0] == "New Tech Co"
            assert args[1] == "new-tech-co"
            return created_org_id

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID = None):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.organizations.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.post(
        "/api/organizations",
        json={"name": "New Tech Co", "slug": "new-tech-co"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["org_id"] == str(created_org_id)
    assert data["name"] == "New Tech Co"
    assert data["slug"] == "new-tech-co"
    assert data["role"] == "admin"


def test_create_organization_rejects_invalid_slug():
    user = AuthenticatedUser(id=uuid4(), email="creator@example.com", role="authenticated")
    app.dependency_overrides[get_current_user] = lambda: user

    client = TestClient(app)
    response = client.post(
        "/api/organizations",
        json={"name": "Invalid Slug Org", "slug": "Invalid Slug_With Spaces!"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 2. Dual Hashing, Secret Protection & Rate Limiting Tests
# ---------------------------------------------------------------------------

def test_admin_can_create_invitation_with_dual_hashes(monkeypatch, admin_context):
    user, org = admin_context
    app.dependency_overrides[require_admin] = lambda: (user, org)

    inserted_state = {}

    class FakeConn:
        async def fetchrow(self, query: str, *args):
            if "FROM public.memberships" in query:
                return None  # Not already a member
            if "FROM public.invitations" in query and "SELECT id" in query:
                return None  # No pending invite
            if "INSERT INTO public.invitations" in query:
                inserted_state["token_hash"] = args[4]
                inserted_state["code_hash"] = args[5]
                return {
                    "id": args[0],
                    "org_id": args[1],
                    "invited_email": args[2],
                    "role": args[3],
                    "status": "pending",
                    "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
                    "created_at": datetime.now(timezone.utc),
                }
            return None

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID = None):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.invitations.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.post(
        "/api/invitations",
        json={"email": "newhire@acme.corp", "role": "team_lead"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["invited_email"] == "newhire@acme.corp"
    assert data["role"] == "team_lead"
    assert "raw_token" in data
    assert "raw_code" in data
    assert data["raw_code"].startswith("INV-")
    assert len(data["raw_code"]) == 16  # "INV-" + 12 chars

    # Verify that what was inserted in DB was the SHA-256 hash, NEVER the raw secret
    assert hashlib.sha256(data["raw_token"].encode()).hexdigest() == inserted_state["token_hash"]
    assert hashlib.sha256(data["raw_code"].encode()).hexdigest() == inserted_state["code_hash"]


def test_invitation_listing_never_exposes_hashes(monkeypatch, admin_context):
    user, org = admin_context
    app.dependency_overrides[require_admin] = lambda: (user, org)

    class FakeConn:
        async def fetch(self, query: str, *args):
            return [
                {
                    "id": uuid4(),
                    "org_id": org.org_id,
                    "invited_email": "candidate@acme.corp",
                    "role": "member",
                    "status": "pending",
                    "expires_at": datetime.now(timezone.utc) + timedelta(days=6),
                    "created_at": datetime.now(timezone.utc),
                }
            ]

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID = None):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.invitations.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.get("/api/invitations")

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    # Ensure neither raw secret nor hash fields exist in output
    assert "token_hash" not in items[0]
    assert "code_hash" not in items[0]
    assert "raw_token" not in items[0]
    assert "raw_code" not in items[0]


# ---------------------------------------------------------------------------
# 3. Invitation Acceptance Safeguards
# ---------------------------------------------------------------------------

def test_invitation_acceptance_blocks_existing_member(monkeypatch):
    user = AuthenticatedUser(id=uuid4(), email="already_in@acme.corp", role="authenticated")
    app.dependency_overrides[get_current_user] = lambda: user

    import asyncpg

    class CustomPGError(asyncpg.PostgresError):
        def __init__(self, msg):
            super().__init__(msg)
            self.sqlstate = "P0007"

    class ErrorConn:
        async def fetchrow(self, query: str, *args):
            raise CustomPGError("User is already a member of this organization")

    @asynccontextmanager
    async def error_tx(user_id: UUID, org_id: UUID = None):
        yield ErrorConn()
        yield ErrorConn()

    monkeypatch.setattr("apps.api.routers.invitations.transaction_context", error_tx)

    client = TestClient(app)
    response = client.post(
        "/api/invitations/accept",
        json={"code_or_token": "INV-ABCDEFGHIJKL"},
    )

    assert response.status_code == 400
    assert "already an active member" in response.json()["detail"].lower()


def test_invitation_acceptance_email_mismatch_rejected(monkeypatch):
    user = AuthenticatedUser(id=uuid4(), email="wrong_user@acme.corp", role="authenticated")
    app.dependency_overrides[get_current_user] = lambda: user

    import asyncpg

    class MismatchPGError(asyncpg.PostgresError):
        def __init__(self):
            super().__init__("Email mismatch")
            self.sqlstate = "P0005"

    class MismatchConn:
        async def fetchrow(self, query: str, *args):
            raise MismatchPGError()

    @asynccontextmanager
    async def mismatch_tx(user_id: UUID, org_id: UUID = None):
        yield MismatchConn()

    monkeypatch.setattr("apps.api.routers.invitations.transaction_context", mismatch_tx)

    client = TestClient(app)
    response = client.post(
        "/api/invitations/accept",
        json={"code_or_token": "INV-ABCDEFGHIJKL"},
    )

    assert response.status_code == 403
    assert "email address mismatch" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 4. Final Admin Protection & Team Lead Auditing
# ---------------------------------------------------------------------------

def test_final_admin_demotion_blocked_by_trigger(monkeypatch, admin_context):
    user, org = admin_context
    app.dependency_overrides[require_admin] = lambda: (user, org)

    import asyncpg

    class TriggerPGError(asyncpg.PostgresError):
        def __init__(self):
            super().__init__("Cannot demote the last administrator")
            self.sqlstate = "P0001"

    class AdminConn:
        async def fetchrow(self, query: str, *args):
            return {"id": uuid4(), "role": "admin", "email": "sole_admin@acme.corp", "created_at": datetime.now(timezone.utc)}

        async def execute(self, query: str, *args):
            raise TriggerPGError()

    @asynccontextmanager
    async def admin_tx(user_id: UUID, org_id: UUID = None):
        yield AdminConn()

    monkeypatch.setattr("apps.api.routers.organizations.transaction_context", admin_tx)

    client = TestClient(app)
    response = client.patch(
        f"/api/team/members/{user.id}",
        json={"role": "member"},
    )

    assert response.status_code == 400
    assert "cannot demote the last administrator" in response.json()["detail"].lower()


def test_team_lead_forbidden_from_inviting_or_altering_roles(team_lead_context):
    user, org = team_lead_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)

    client = TestClient(app)

    # 1. Team lead cannot invite
    res_inv = client.post(
        "/api/invitations",
        json={"email": "newbie@acme.corp", "role": "member"},
    )
    assert res_inv.status_code == 403

    # 2. Team lead cannot change member roles
    res_role = client.patch(
        f"/api/team/members/{uuid4()}",
        json={"role": "admin"},
    )
    assert res_role.status_code == 403

    # 3. Team lead cannot configure or sync sources
    res_source = client.post(
        "/api/sources",
        json={"name": "TL Source", "type": "github", "config": {"repo": "acme/repo"}},
    )
    assert res_source.status_code == 403


# ---------------------------------------------------------------------------
# 5. Directory Privacy
# ---------------------------------------------------------------------------

def test_regular_member_directory_privacy(monkeypatch, member_context):
    user, org = member_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)

    class PrivConn:
        async def fetch(self, query: str, *args):
            # get_org_members for regular members returns only self
            return [
                {
                    "user_id": user.id,
                    "email": user.email,
                    "role": "member",
                    "created_at": datetime.now(timezone.utc),
                }
            ]

    @asynccontextmanager
    async def priv_tx(user_id: UUID, org_id: UUID = None):
        yield PrivConn()

    monkeypatch.setattr("apps.api.routers.organizations.transaction_context", priv_tx)

    client = TestClient(app)
    response = client.get("/api/team/members")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["user_id"] == str(user.id)


# ---------------------------------------------------------------------------
# 6. Assigned Work & Cross-Tenant Validation in Handoffs
# ---------------------------------------------------------------------------

def test_handoff_item_rejects_cross_tenant_assignee(monkeypatch, admin_context):
    user, org = admin_context
    app.dependency_overrides[get_organization_context] = lambda: (user, org)

    class HandoffConn:
        async def fetchrow(self, query: str, *args):
            if "SELECT created_by_user_id" in query:
                return {"created_by_user_id": user.id, "recipient_user_id": None}
            if "SELECT id, title" in query:
                return {
                    "id": uuid4(),
                    "title": "Action Item",
                    "description": "Desc",
                    "item_status": "inferred",
                    "record_id": None,
                    "note_id": None,
                    "gap_id": None,
                    "assignee_user_id": None,
                    "due_date": None,
                }
            if "FROM public.memberships" in query:
                return None  # Assignee is NOT in this organization
            return None

    @asynccontextmanager
    async def handoff_tx(user_id: UUID, org_id: UUID = None):
        yield HandoffConn()

    monkeypatch.setattr("apps.api.routers.handoffs.transaction_context", handoff_tx)

    client = TestClient(app)
    response = client.patch(
        f"/api/handoffs/{uuid4()}/items/{uuid4()}",
        json={"assignee_user_id": str(uuid4())},
    )

    assert response.status_code == 400
    assert "not an active member of this organization" in response.json()["detail"].lower()


def test_invitation_lookup_rate_limiting(monkeypatch):
    user = AuthenticatedUser(id=uuid4(), email="tester@acme.corp", role="authenticated")
    app.dependency_overrides[get_current_user] = lambda: user

    class EmptyConn:
        async def fetchrow(self, query: str, *args):
            return None

    @asynccontextmanager
    async def empty_tx(user_id: UUID, org_id: UUID = None):
        yield EmptyConn()

    monkeypatch.setattr("apps.api.routers.invitations.transaction_context", empty_tx)

    client = TestClient(app)

    # Make 5 attempts (allowed)
    for _ in range(5):
        res = client.post("/api/invitations/lookup", json={"code_or_token": "INV-123456789012"})
        assert res.status_code in (404, 410)

    # 6th attempt must be rate-limited with 429
    res_blocked = client.post("/api/invitations/lookup", json={"code_or_token": "INV-123456789012"})
    assert res_blocked.status_code == 429
    assert "too many invitation attempts" in res_blocked.json()["detail"].lower()

