"""
Unit tests for Supabase Auth JWT verification and endpoint authentication.
"""

from __future__ import annotations

import time
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

from apps.api.auth.jwt import verify_supabase_jwt
from apps.api.config import settings
from apps.api.main import app

# Shared test secret
TEST_SECRET = "test-supabase-jwt-secret-very-secure-32chars"


@pytest.fixture(autouse=True)
def setup_test_jwt_secret(monkeypatch):
    """Ensure test JWT secret is configured for all tests in this module."""
    from pydantic import SecretStr
    monkeypatch.setattr(settings, "supabase_jwt_secret", SecretStr(TEST_SECRET))
    monkeypatch.setattr(settings, "supabase_url", "https://test-project.supabase.co")


def make_test_jwt(
    sub: str | None = None,
    iss: str = "supabase",
    exp_offset: int = 3600,
    secret: str = TEST_SECRET,
    alg: str = "HS256",
    email: str = "engineer@example.com",
    role: str = "authenticated",
) -> str:
    """Helper to generate JWT tokens with various claims for testing."""
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + exp_offset,
        "iss": iss,
        "email": email,
        "role": role,
    }
    if sub is not None:
        payload["sub"] = sub

    headers = {"alg": alg, "typ": "JWT"}
    return jwt.encode(payload, secret, algorithm=alg, headers=headers)


@pytest.mark.asyncio
async def test_valid_jwt_verification():
    user_id = str(uuid4())
    token = make_test_jwt(sub=user_id)
    user = await verify_supabase_jwt(token)
    assert str(user.id) == user_id
    assert user.email == "engineer@example.com"
    assert user.role == "authenticated"


@pytest.mark.asyncio
async def test_expired_jwt_rejected():
    user_id = str(uuid4())
    token = make_test_jwt(sub=user_id, exp_offset=-60)  # expired 60s ago
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401
    assert "verification failed or token expired" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_invalid_signature_rejected():
    user_id = str(uuid4())
    token = make_test_jwt(sub=user_id, secret="wrong-secret-key-that-does-not-match")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_wrong_issuer_rejected():
    user_id = str(uuid4())
    token = make_test_jwt(sub=user_id, iss="malicious-auth-provider.com")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401
    assert "issuer is invalid" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_missing_sub_rejected():
    token = make_test_jwt(sub=None)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401
    assert "subject claim is missing" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_invalid_uuid_sub_rejected():
    token = make_test_jwt(sub="not-a-valid-uuid")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401
    assert "not a valid uuid" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_algorithm_none_rejected():
    # Construct an unsigned token with alg=none manually
    import base64
    import json
    h_b64 = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').decode().rstrip("=")
    p_b64 = base64.urlsafe_b64encode(json.dumps({"sub": str(uuid4()), "iss": "supabase"}).encode()).decode().rstrip("=")
    token = f"{h_b64}.{p_b64}."
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401
    assert "invalid token algorithm" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_malformed_token_rejected():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await verify_supabase_jwt("not.a.valid.jwt.payload")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_jwt_secret_fails_closed(monkeypatch):
    from pydantic import SecretStr
    monkeypatch.setattr(settings, "supabase_jwt_secret", SecretStr(""))
    user_id = str(uuid4())
    token = make_test_jwt(sub=user_id)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await verify_supabase_jwt(token)
    assert exc_info.value.status_code == 500
    assert "misconfigured" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_public_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_protected_me_endpoint_unauthorized():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/me")
        assert resp.status_code == 401
        assert "authentication required" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_protected_me_endpoint_authorized():
    user_id = str(uuid4())
    token = make_test_jwt(sub=user_id, email="dev@company.com")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == user_id
        assert data["email"] == "dev@company.com"


@pytest.mark.asyncio
async def test_algorithm_confusion_rejected(monkeypatch):
    """When configured for HS256, tokens advertising RS256 must be rejected immediately."""
    monkeypatch.setattr(settings, "supabase_jwt_algorithm", "HS256")
    import base64
    import json
    h_b64 = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}').decode().rstrip("=")
    p_b64 = base64.urlsafe_b64encode(json.dumps({"sub": str(uuid4()), "iss": "supabase"}).encode()).decode().rstrip("=")
    token = f"{h_b64}.{p_b64}.fake-sig"
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401
    assert "does not match expected algorithm" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_jwks_failure_fails_closed_no_hs256_fallback(monkeypatch):
    """When configured for RS256, if JWKS fails, it must fail closed and never fall back to HS256."""
    monkeypatch.setattr(settings, "supabase_jwt_algorithm", "RS256")
    import base64
    import json
    h_b64 = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT","kid":"test-key"}').decode().rstrip("=")
    p_b64 = base64.urlsafe_b64encode(json.dumps({"sub": str(uuid4()), "iss": "supabase"}).encode()).decode().rstrip("=")
    token = f"{h_b64}.{p_b64}.fake-sig"

    async def mock_failing_jwks():
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication configuration error: unable to load public signing keys",
        )

    monkeypatch.setattr("apps.api.auth.jwt._fetch_jwks", mock_failing_jwks)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await verify_supabase_jwt(token)
    assert exc_info.value.status_code == 500
    assert "unable to load public signing keys" in exc_info.value.detail.lower()
