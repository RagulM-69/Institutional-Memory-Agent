"""
Unit tests for organization resolution and membership authorization.
Tests mock database records to test all authorization logic paths deterministically.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from apps.api.auth.dependencies import (
    ActiveOrganization,
    AuthenticatedUser,
    get_organization_context,
    require_admin,
)


class MockDbRecord(dict):
    """Dictionary mimicking asyncpg.Record access."""
    def __getitem__(self, key):
        return super().__getitem__(key)


@asynccontextmanager
async def mock_transaction_context(records: list[dict]):
    class FakeConn:
        async def fetch(self, query: str, *args):
            return records
    yield FakeConn()


@pytest.fixture
def auth_user():
    return AuthenticatedUser(
        id=uuid4(),
        email="eng@example.com",
        role="authenticated",
    )


@pytest.mark.asyncio
async def test_user_with_no_memberships_forbidden(auth_user, monkeypatch):
    @asynccontextmanager
    async def fake_ctx(user_id=None, org_id=None, connection=None):
        class FakeConn:
            async def fetch(self, query, *args):
                return []
        yield FakeConn()

    monkeypatch.setattr("apps.api.auth.dependencies.transaction_context", fake_ctx)

    with pytest.raises(HTTPException) as exc_info:
        await get_organization_context(user=auth_user, x_organization_id=None)
    assert exc_info.value.status_code == 403
    assert "not a member of any organization" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_user_with_single_membership_auto_selected(auth_user, monkeypatch):
    org_id = uuid4()
    mock_records = [
        MockDbRecord({
            "org_id": org_id,
            "role": "member",
            "name": "Acme Corp",
            "slug": "acme-corp",
        })
    ]

    @asynccontextmanager
    async def fake_ctx(user_id=None, org_id=None, connection=None):
        class FakeConn:
            async def fetch(self, query, *args):
                return mock_records
        yield FakeConn()

    monkeypatch.setattr("apps.api.auth.dependencies.transaction_context", fake_ctx)

    user, org = await get_organization_context(user=auth_user, x_organization_id=None)
    assert user.id == auth_user.id
    assert org.org_id == org_id
    assert org.name == "Acme Corp"
    assert org.slug == "acme-corp"
    assert org.role == "member"


@pytest.mark.asyncio
async def test_user_with_single_membership_wrong_header_forbidden(auth_user, monkeypatch):
    org_id = uuid4()
    wrong_org_id = str(uuid4())
    mock_records = [
        MockDbRecord({
            "org_id": org_id,
            "role": "member",
            "name": "Acme Corp",
            "slug": "acme-corp",
        })
    ]

    @asynccontextmanager
    async def fake_ctx(user_id=None, org_id=None, connection=None):
        class FakeConn:
            async def fetch(self, query, *args):
                return mock_records
        yield FakeConn()

    monkeypatch.setattr("apps.api.auth.dependencies.transaction_context", fake_ctx)

    with pytest.raises(HTTPException) as exc_info:
        await get_organization_context(user=auth_user, x_organization_id=wrong_org_id)
    assert exc_info.value.status_code == 403
    assert "not an active member of the requested organization" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_user_with_multiple_memberships_no_header_bad_request(auth_user, monkeypatch):
    mock_records = [
        MockDbRecord({"org_id": uuid4(), "role": "admin", "name": "Org 1", "slug": "org-1"}),
        MockDbRecord({"org_id": uuid4(), "role": "member", "name": "Org 2", "slug": "org-2"}),
    ]

    @asynccontextmanager
    async def fake_ctx(user_id=None, org_id=None, connection=None):
        class FakeConn:
            async def fetch(self, query, *args):
                return mock_records
        yield FakeConn()

    monkeypatch.setattr("apps.api.auth.dependencies.transaction_context", fake_ctx)

    with pytest.raises(HTTPException) as exc_info:
        await get_organization_context(user=auth_user, x_organization_id=None)
    assert exc_info.value.status_code == 400
    assert "belongs to multiple organizations" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_user_with_multiple_memberships_valid_header_selected(auth_user, monkeypatch):
    target_org_id = uuid4()
    mock_records = [
        MockDbRecord({"org_id": uuid4(), "role": "member", "name": "Org 1", "slug": "org-1"}),
        MockDbRecord({"org_id": target_org_id, "role": "admin", "name": "Target Org", "slug": "target-org"}),
    ]

    @asynccontextmanager
    async def fake_ctx(user_id=None, org_id=None, connection=None):
        class FakeConn:
            async def fetch(self, query, *args):
                return mock_records
        yield FakeConn()

    monkeypatch.setattr("apps.api.auth.dependencies.transaction_context", fake_ctx)

    user, org = await get_organization_context(user=auth_user, x_organization_id=str(target_org_id))
    assert org.org_id == target_org_id
    assert org.name == "Target Org"
    assert org.role == "admin"


@pytest.mark.asyncio
async def test_user_with_multiple_memberships_unauthorized_header_forbidden(auth_user, monkeypatch):
    unauthorized_org_id = str(uuid4())
    mock_records = [
        MockDbRecord({"org_id": uuid4(), "role": "member", "name": "Org 1", "slug": "org-1"}),
        MockDbRecord({"org_id": uuid4(), "role": "member", "name": "Org 2", "slug": "org-2"}),
    ]

    @asynccontextmanager
    async def fake_ctx(user_id=None, org_id=None, connection=None):
        class FakeConn:
            async def fetch(self, query, *args):
                return mock_records
        yield FakeConn()

    monkeypatch.setattr("apps.api.auth.dependencies.transaction_context", fake_ctx)

    with pytest.raises(HTTPException) as exc_info:
        await get_organization_context(user=auth_user, x_organization_id=unauthorized_org_id)
    assert exc_info.value.status_code == 403
    assert "not an active member of the requested organization" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_invalid_uuid_header_bad_request(auth_user):
    with pytest.raises(HTTPException) as exc_info:
        await get_organization_context(user=auth_user, x_organization_id="not-a-valid-uuid")
    assert exc_info.value.status_code == 400
    assert "invalid x-organization-id header format" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_require_admin_allows_admin(auth_user):
    org = ActiveOrganization(org_id=uuid4(), name="Test Org", slug="test-org", role="admin")
    result_user, result_org = await require_admin((auth_user, org))
    assert result_org.role == "admin"


@pytest.mark.asyncio
async def test_require_admin_rejects_member(auth_user):
    org = ActiveOrganization(org_id=uuid4(), name="Test Org", slug="test-org", role="member")
    with pytest.raises(HTTPException) as exc_info:
        await require_admin((auth_user, org))
    assert exc_info.value.status_code == 403
    assert "administrator privileges required" in exc_info.value.detail.lower()

