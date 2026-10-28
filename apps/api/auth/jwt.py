"""
Supabase Auth JWT verification module.
Supports both asymmetric keys (RS256/ES256 via JWKS) and symmetric secret (HS256).
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from apps.api.config import settings

logger = logging.getLogger(__name__)

# Cached JWKS keys with TTL
_jwks_cache: dict[str, Any] = {}
_jwks_last_fetched: float = 0.0
_JWKS_CACHE_TTL_SECONDS = 600  # 10 minutes


class AuthenticatedUser(BaseModel):
    """Represents a cryptographically verified Supabase Auth user."""
    id: UUID
    email: str | None = None
    role: str = "authenticated"
    app_metadata: dict[str, Any] = Field(default_factory=dict)
    user_metadata: dict[str, Any] = Field(default_factory=dict)


def _get_expected_issuers() -> list[str]:
    """Return acceptable JWT issuer strings for this Supabase project."""
    issuers = ["supabase"]
    if settings.supabase_url:
        base = settings.supabase_url.rstrip("/")
        issuers.append(f"{base}/auth/v1")
        issuers.append(base)
    return issuers


async def _fetch_jwks() -> dict[str, Any]:
    """Fetch and cache JWKS from Supabase Auth."""
    global _jwks_cache, _jwks_last_fetched
    now = time.time()
    if _jwks_cache and (now - _jwks_last_fetched < _JWKS_CACHE_TTL_SECONDS):
        return _jwks_cache

    jwks_url = settings.supabase_jwks_url
    if not jwks_url and settings.supabase_url:
        jwks_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    if not jwks_url:
        raise RuntimeError("Neither SUPABASE_JWKS_URL nor SUPABASE_URL is configured for JWKS resolution")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            data = response.json()
            _jwks_cache = data
            _jwks_last_fetched = now
            return data
    except Exception as e:
        logger.error("Failed to fetch Supabase JWKS from %s: %s", jwks_url, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication configuration error: unable to load public signing keys",
        ) from e


async def verify_supabase_jwt(token: str) -> AuthenticatedUser:
    """
    Verify and decode a Supabase Auth JWT token.

    Validates:
    - Algorithm (rejects 'none' and unsupported algos)
    - Signature (via JWKS for RS256/ES256, or SUPABASE_JWT_SECRET for HS256)
    - Issuer (must match expected project issuer)
    - Expiration (rejects expired tokens)
    - Subject (must be a valid UUID)
    """
    if not token or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed authentication token header",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    alg = unverified_header.get("alg")
    if not alg or alg.lower() == "none":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token algorithm",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Enforce configured algorithm to prevent algorithm confusion attacks.
    # Accepts comma-separated algorithms (e.g. "HS256,ES256") or single algorithm.
    allowed_algs = [
        a.strip().upper()
        for a in (settings.supabase_jwt_algorithm or "HS256,ES256,RS256").split(",")
        if a.strip()
    ]
    if alg.upper() not in allowed_algs:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token algorithm '{alg}' does not match expected algorithm '{settings.supabase_jwt_algorithm}'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    expected_issuers = _get_expected_issuers()

    # Strategy 1: Asymmetric signing (RS256, ES256) via JWKS
    if alg in ("RS256", "ES256"):
        kid = unverified_header.get("kid")
        jwks = await _fetch_jwks()
        keys = jwks.get("keys", [])
        matched_key = None
        for k in keys:
            if k.get("kid") == kid or (not kid and len(keys) == 1):
                matched_key = k
                break

        if not matched_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to find matching public key for token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            payload = jwt.decode(
                token,
                matched_key,
                algorithms=[alg],
                options={"verify_exp": True, "verify_iss": False, "verify_aud": False},
            )
        except JWTError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token signature verification failed or token expired",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

    # Strategy 2: Symmetric signing (HS256) via SUPABASE_JWT_SECRET
    elif alg == "HS256":
        secret = settings.supabase_jwt_secret.get_secret_value()
        if not secret:
            logger.error("SUPABASE_JWT_SECRET is not configured for HS256 token verification")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication service misconfigured: missing JWT secret",
            )

        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                options={"verify_exp": True, "verify_iss": False, "verify_aud": False},
            )
        except JWTError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token signature verification failed or token expired",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unsupported token algorithm: {alg}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate Audience if present
    token_aud = payload.get("aud")
    if token_aud and token_aud not in ("authenticated", "anon"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token audience is invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate Issuer
    token_iss = payload.get("iss")
    if token_iss and token_iss not in expected_issuers:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token issuer is invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate Subject (User UUID)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject claim is missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = UUID(str(sub))
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject is not a valid UUID",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    user_meta = payload.get("user_metadata", {})
    email_val = payload.get("email") or (user_meta.get("email") if isinstance(user_meta, dict) else None)

    return AuthenticatedUser(
        id=user_uuid,
        email=email_val,
        role=payload.get("role", "authenticated"),
        app_metadata=payload.get("app_metadata", {}),
        user_metadata=user_meta if isinstance(user_meta, dict) else {},
    )

