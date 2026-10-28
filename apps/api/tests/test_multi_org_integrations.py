"""
Comprehensive tests for Multi-Organization Integrations (GitHub, Jira, Slack):
1. OAuth provider status reporting & missing environment variable detection
2. Secure signed OAuth state generation & CSRF / tampering prevention
3. Organization isolation: OAuth sessions belonging to Org A cannot be read or finalized by Org B
4. AES-256-GCM tenant-bound encrypted credentials at rest
5. Cross-organization credential tampering: ciphertext cannot be decrypted under another org_id
6. Token secrecy: encrypted credentials are never exposed in list or detail API responses
7. Duplicate source connection prevention (HTTP 409 Conflict)
8. Ingestion pipeline decryption & connector token passing in worker context
"""

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.auth.crypto import (
    DecryptionError,
    decrypt_credentials,
    encrypt_credentials,
)
from apps.api.auth.dependencies import (
    ActiveOrganization,
    AuthenticatedUser,
    get_organization_context,
    require_admin,
)
from apps.api.config import settings
from apps.api.connectors.base import FetchResult, NormalizedRecord, ValidationResult
from apps.api.ingest.pipeline import IngestPipeline
from apps.api.main import app
from apps.api.routers.sources import (
    OAuthSession,
    _create_oauth_state,
    _oauth_sessions,
    _verify_oauth_state,
)


@pytest.fixture
def org_a_admin():
    user = AuthenticatedUser(id=uuid4(), email="admin@org-a.corp", role="authenticated")
    org = ActiveOrganization(org_id=uuid4(), name="Org Alpha", slug="org-alpha", role="admin")
    return user, org


@pytest.fixture
def org_b_admin():
    user = AuthenticatedUser(id=uuid4(), email="admin@org-b.corp", role="authenticated")
    org = ActiveOrganization(org_id=uuid4(), name="Org Beta", slug="org-beta", role="admin")
    return user, org


@pytest.fixture
def org_a_member():
    user = AuthenticatedUser(id=uuid4(), email="dev@org-a.corp", role="authenticated")
    org = ActiveOrganization(org_id=uuid4(), name="Org Alpha", slug="org-alpha", role="member")
    return user, org


@pytest.fixture(autouse=True)
def clean_state():
    app.dependency_overrides.clear()
    _oauth_sessions.clear()
    yield
    app.dependency_overrides.clear()
    _oauth_sessions.clear()


# ---------------------------------------------------------------------------
# 1. Cryptographic Security & Tenant Isolation Tests
# ---------------------------------------------------------------------------

def test_aes_gcm_credential_encryption_and_decryption():
    org_id = uuid4()
    source_id = uuid4()
    payload = {"token": "ghp_test_secret_pat_998877", "account": "octocat"}

    encrypted = encrypt_credentials(payload, org_id, source_id)
    assert isinstance(encrypted, bytes)
    assert len(encrypted) > 29  # 1B version + 12B nonce + 16B tag + ciphertext

    decrypted = decrypt_credentials(encrypted, org_id, source_id)
    assert decrypted == payload


def test_cross_tenant_credential_decryption_fails():
    org_a = uuid4()
    org_b = uuid4()
    source_id = uuid4()
    payload = {"token": "xoxb-slack-secret-token"}

    encrypted = encrypt_credentials(payload, org_a, source_id)

    # Attempting to decrypt with Org B must fail authentication tag check
    with pytest.raises(DecryptionError):
        decrypt_credentials(encrypted, org_b, source_id)


def test_tampered_credential_ciphertext_fails():
    org_id = uuid4()
    source_id = uuid4()
    payload = {"token": "jira_secret_token"}

    encrypted = bytearray(encrypt_credentials(payload, org_id, source_id))
    # Tamper with the last byte of ciphertext/tag
    encrypted[-1] ^= 0xFF

    with pytest.raises(DecryptionError):
        decrypt_credentials(bytes(encrypted), org_id, source_id)


# ---------------------------------------------------------------------------
# 2. OAuth State Signing & Tamper Verification Tests
# ---------------------------------------------------------------------------

def test_oauth_state_creation_and_valid_verification():
    org_id = uuid4()
    user_id = uuid4()

    state = _create_oauth_state(org_id, user_id, "github")
    verified_org, verified_user = _verify_oauth_state(state, "github")

    assert verified_org == org_id
    assert verified_user == user_id


def test_oauth_state_tampering_rejected():
    org_id = uuid4()
    user_id = uuid4()

    state = _create_oauth_state(org_id, user_id, "github")
    # Tamper with the base64 string
    tampered = state[:-4] + "AAAA"

    with pytest.raises(Exception):
        _verify_oauth_state(tampered, "github")


def test_oauth_state_provider_mismatch_rejected():
    org_id = uuid4()
    user_id = uuid4()

    state = _create_oauth_state(org_id, user_id, "github")

    # Verifying for jira when issued for github must fail
    with pytest.raises(Exception):
        _verify_oauth_state(state, "jira")


# ---------------------------------------------------------------------------
# 3. OAuth Provider Status & Authorize Endpoint Tests
# ---------------------------------------------------------------------------

def test_oauth_status_endpoint_reports_availability(org_a_admin):
    user, org = org_a_admin
    app.dependency_overrides[get_organization_context] = lambda: (user, org)

    client = TestClient(app)
    response = client.get("/api/sources/oauth/status")
    assert response.status_code == 200
    data = response.json()

    assert "providers" in data
    assert "github" in data["providers"]
    assert "jira" in data["providers"]
    assert "slack" in data["providers"]

    for prov in ("github", "jira", "slack"):
        info = data["providers"][prov]
        assert "available" in info
        assert "missing_env_vars" in info
        assert "redirect_uri" in info


def test_oauth_authorize_unconfigured_provider_fails_safely(org_a_admin, monkeypatch):
    user, org = org_a_admin
    app.dependency_overrides[require_admin] = lambda: (user, org)

    # Force GITHUB_CLIENT_ID to be empty
    monkeypatch.setattr(settings, "github_client_id", "")

    client = TestClient(app)
    response = client.get("/api/sources/oauth/github/authorize")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "GITHUB_CLIENT_ID" in detail


# ---------------------------------------------------------------------------
# 4. OAuth Session Isolation Between Organizations
# ---------------------------------------------------------------------------

def test_oauth_session_tenant_isolation(org_a_admin, org_b_admin):
    user_a, org_a = org_a_admin
    user_b, org_b = org_b_admin

    # Establish an OAuth session for Org A
    session_id = uuid4().hex
    _oauth_sessions[session_id] = OAuthSession(
        session_id=session_id,
        org_id=org_a.org_id,
        user_id=user_a.id,
        provider="github",
        account_name="alpha-corp-gh",
        credentials={"token": "ghp_alpha_token"},
        targets=[{"id": "alpha/repo-1", "name": "repo-1"}],
    )

    client = TestClient(app)

    # 1. Org A Admin can view the session
    app.dependency_overrides[require_admin] = lambda: (user_a, org_a)
    resp_a = client.get(f"/api/sources/oauth/session/{session_id}")
    assert resp_a.status_code == 200
    assert resp_a.json()["account_name"] == "alpha-corp-gh"
    # Verify token is NEVER returned
    assert "credentials" not in resp_a.json()
    assert "token" not in str(resp_a.json())

    # 2. Org B Admin attempting to access Org A's session receives 404
    app.dependency_overrides[require_admin] = lambda: (user_b, org_b)
    resp_b = client.get(f"/api/sources/oauth/session/{session_id}")
    assert resp_b.status_code == 404


# ---------------------------------------------------------------------------
# 5. Create Source with Encrypted Credentials & Secrecy Tests
# ---------------------------------------------------------------------------

def test_create_source_with_direct_encrypted_credentials(monkeypatch, org_a_admin):
    user, org = org_a_admin
    app.dependency_overrides[require_admin] = lambda: (user, org)

    # Mock connector validation so it succeeds without hitting external APIs
    async def fake_validate(self):
        return ValidationResult(is_valid=True, message="Connected to GitHub repository successfully")

    monkeypatch.setattr("apps.api.connectors.github.GitHubConnector.validate", fake_validate)

    created_record: Dict[str, Any] = {}

    class FakeConn:
        async def execute(self, query: str, *args):
            if "INSERT INTO public.sources" in query:
                created_record["id"] = args[0]
                created_record["org_id"] = args[1]
                created_record["name"] = args[2]
                created_record["type"] = args[3]
                created_record["visibility"] = args[4]
                created_record["config"] = json.loads(args[5])
                created_record["encrypted_credentials"] = args[6]
            return "INSERT 0 1"

        async def fetchrow(self, query: str, *args):
            if "WHERE id = $1 AND org_id = $2" in query:
                return {
                    "id": created_record["id"],
                    "org_id": created_record["org_id"],
                    "name": created_record["name"],
                    "type": created_record["type"],
                    "visibility": created_record["visibility"],
                    "config": json.dumps(created_record["config"]),
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
            "name": "Secure Alpha Repo",
            "type": "github",
            "visibility": "public",
            "config": {"repo": "alpha/secure-repo"},
            "credentials": {"token": "ghp_my_secret_token_123"},
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["has_encrypted_credentials"] is True
    # Verify raw token is NOT in config or response
    assert "token" not in data["config"]
    assert "ghp_my_secret_token_123" not in json.dumps(data)

    # Verify that in database, encrypted_credentials was stored encrypted
    enc_bytes = created_record["encrypted_credentials"]
    assert isinstance(enc_bytes, bytes)
    # Decrypt with correct org_id and source_id
    decrypted = decrypt_credentials(enc_bytes, org.org_id, created_record["id"])
    assert decrypted["token"] == "ghp_my_secret_token_123"


# ---------------------------------------------------------------------------
# 6. Duplicate Source Connection Prevention
# ---------------------------------------------------------------------------

def test_duplicate_github_connection_rejected_with_409(monkeypatch, org_a_admin):
    user, org = org_a_admin
    app.dependency_overrides[require_admin] = lambda: (user, org)

    class FakeConn:
        async def fetchrow(self, query: str, *args):
            # Duplicate check query finds existing row
            if "type = 'github' AND is_archived = false AND config->>'repo'" in query:
                return {"id": uuid4(), "name": "Existing Repo Source"}
            return None

    @asynccontextmanager
    async def fake_tx(user_id: UUID, org_id: UUID):
        yield FakeConn()

    monkeypatch.setattr("apps.api.routers.sources.transaction_context", fake_tx)

    client = TestClient(app)
    response = client.post(
        "/api/sources",
        json={
            "name": "Duplicate Repo Attempt",
            "type": "github",
            "visibility": "public",
            "config": {"repo": "alpha/monorepo"},
        },
    )

    assert response.status_code == 409
    assert "already connected" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 7. Ingestion Pipeline Decrypts Credentials for Worker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_decrypts_stored_credentials_for_connector():
    org_id = uuid4()
    source_id = uuid4()
    token = "ghp_verified_worker_token"
    enc_creds = encrypt_credentials({"token": token}, org_id, source_id)

    passed_token = None

    class MockGitHubConnector:
        def __init__(self, repo: str, token: str = None):
            nonlocal passed_token
            passed_token = token

        async def fetch(self, cursor=None, limit=None):
            return FetchResult(records=[], new_cursor={}, has_more=False)

    class FakeConn:
        async def fetchrow(self, query: str, *args):
            return {
                "id": source_id,
                "name": "Pipeline Source",
                "type": "github",
                "config": json.dumps({"repo": "org/repo"}),
                "encrypted_credentials": enc_creds,
                "sync_cursor": {},
                "sync_status": "ok",
            }

        async def execute(self, query: str, *args):
            return "UPDATE 1"

    pipeline = IngestPipeline()

    import apps.api.ingest.pipeline as pipe_mod
    orig_connector = pipe_mod.GitHubConnector
    pipe_mod.GitHubConnector = MockGitHubConnector

    try:
        report = await pipeline.sync_source(
            source_id=source_id,
            org_id=org_id,
            connection=FakeConn(),
        )
        assert report.status == "ok"
        assert passed_token == token
    finally:
        pipe_mod.GitHubConnector = orig_connector

