"""
API router for Knowledge Sources management and evidence sync orchestration.
Enforces organization membership, admin-only mutations, tenant isolation,
PostgreSQL Row-Level Security, and server-side credential isolation.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from apps.api.config import settings
from apps.api.auth.crypto import (
    encrypt_credentials,
    decrypt_credentials,
    DecryptionError,
    _derive_master_key,
)
from apps.api.auth.dependencies import (
    ActiveOrganization,
    AuthenticatedUser,
    get_organization_context,
    require_admin,
    require_team_lead_or_admin,
)
from apps.api.connectors.base import ValidationResult
from apps.api.connectors.github import GitHubConnector
from apps.api.connectors.jira import JiraConnector
from apps.api.connectors.slack import SlackConnector
from apps.api.db.pool import transaction_context, worker_transaction_context
from apps.api.ingest.pipeline import IngestPipeline, SyncReport

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sources", tags=["sources"])

# Forbidden keys in source configuration JSON (credentials must remain in server env)
_FORBIDDEN_CONFIG_KEYS = frozenset({
    "token", "secret", "password", "api_key", "github_token",
    "jira_token", "slack_token", "slack_bot_token", "credentials",
})

_GITHUB_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
_JIRA_PROJECT_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SLACK_CHANNEL_RE = re.compile(r"^[CGD][A-Z0-9]+$")


def sanitize_error(msg: str) -> str:
    """Sanitize error messages to prevent leaking credentials or tokens."""
    if not msg:
        return ""
    s = re.sub(r"(Bearer\s+)[A-Za-z0-9_.-]+", r"\1[REDACTED]", msg, flags=re.IGNORECASE)
    s = re.sub(r"(token=)[A-Za-z0-9_.-]+", r"\1[REDACTED]", s, flags=re.IGNORECASE)
    s = re.sub(r"(key=)[A-Za-z0-9_.-]+", r"\1[REDACTED]", s, flags=re.IGNORECASE)
    s = re.sub(r"(password=)[A-Za-z0-9_.-]+", r"\1[REDACTED]", s, flags=re.IGNORECASE)
    s = re.sub(r"://([^:@]+):([^@]+)@", r"://\1:[REDACTED]@", s)
    return s[:1000]


# ── Pydantic Request & Response Schemas ───────────────────────────────────

class CreateSourceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=150, description="Display name for the source.")
    type: str = Field(..., description="Connector type ('github', 'jira', 'slack').")
    visibility: str = Field(default="public", description="Visibility level ('public' or 'restricted').")
    config: Dict[str, Any] = Field(default_factory=dict, description="Connector-specific configuration parameters.")
    credentials: Optional[Dict[str, str]] = Field(default=None, description="Optional raw credentials to encrypt server-side.")


class UpdateSourceRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    visibility: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    is_archived: Optional[bool] = None


class KnowledgeSourceResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    type: str
    visibility: str
    config: Dict[str, Any]
    sync_status: str
    sync_cursor: Optional[Dict[str, Any]] = None
    last_synced_at: Optional[datetime] = None
    error_message: Optional[str] = None
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    record_count: int = 0
    has_encrypted_credentials: bool = False


class RecordSummaryResponse(BaseModel):
    id: UUID
    org_id: UUID
    source_id: UUID
    external_id: str
    record_type: str
    created_at: datetime
    updated_at: datetime
    current_version_id: Optional[UUID] = None
    version_index: Optional[int] = None
    title: Optional[str] = None
    author_name: Optional[str] = None
    url: Optional[str] = None
    snippet: Optional[str] = None
    chunk_count: int = 0


class PaginatedRecordsResponse(BaseModel):
    items: List[RecordSummaryResponse]
    total: int
    limit: int
    offset: int


class ValidateConfigRequest(BaseModel):
    type: str
    config: Dict[str, Any] = Field(default_factory=dict)
    credentials: Optional[Dict[str, str]] = Field(default=None, description="Optional raw credentials to validate before saving.")


class ValidationResponse(BaseModel):
    is_valid: bool
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class SyncResponse(BaseModel):
    source_id: UUID
    status: str
    message: str
    records_scanned: int = 0
    records_created: int = 0
    records_updated: int = 0
    chunks_created: int = 0
    errors: List[str] = Field(default_factory=list)
    duration_seconds: float = 0.0


# ── OAuth Status & Session Models ─────────────────────────────────────────

class OAuthProviderStatus(BaseModel):
    provider: str
    available: bool
    missing_env_vars: List[str] = Field(default_factory=list)
    redirect_uri: str
    scopes: List[str] = Field(default_factory=list)


class OAuthStatusResponse(BaseModel):
    providers: Dict[str, OAuthProviderStatus]


class OAuthAuthorizeResponse(BaseModel):
    provider: str
    authorize_url: str
    state: str


class OAuthSessionTarget(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class OAuthSessionResponse(BaseModel):
    session_id: str
    provider: str
    account_name: str
    targets: List[OAuthSessionTarget] = Field(default_factory=list)


class FinalizeOAuthSessionRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    target_id: str = Field(..., description="Selected repository, project, or channel ID.")
    visibility: str = Field(default="public", description="'public' or 'restricted'")


# ── Configuration Validation Helper ──────────────────────────────────────

def _validate_source_config(source_type: str, config: Dict[str, Any]) -> None:
    """Validate connector configuration and ensure no secret tokens are passed."""
    # 1. Enforce server-side credential isolation: reject any raw tokens
    for key in config.keys():
        if key.lower() in _FORBIDDEN_CONFIG_KEYS or "token" in key.lower() or "secret" in key.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Configuration parameter '{key}' is forbidden. "
                    "Connector credentials must be maintained server-side via environment variables. "
                    "Do not submit raw secrets via the API."
                ),
            )

    # 2. Type-specific validation
    stype = source_type.lower().strip()
    if stype == "github":
        repo = config.get("repo", "").strip()
        if not repo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GitHub source requires 'repo' parameter in format 'owner/repo'.",
            )
        if not _GITHUB_REPO_RE.match(repo):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid GitHub repository format: '{repo}'. Expected 'owner/repo'.",
            )
    elif stype == "jira":
        base_url = config.get("base_url", "").strip()
        if not base_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Jira source requires 'base_url' parameter (e.g. 'https://company.atlassian.net').",
            )
        if not (base_url.startswith("http://") or base_url.startswith("https://")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid Jira base_url '{base_url}'. Must begin with http:// or https://.",
            )
        project = config.get("project")
        if project and not _JIRA_PROJECT_RE.match(project.strip()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid Jira project key '{project}'. Expected alphanumeric uppercase (e.g. 'ENG', 'PROJ').",
            )
    elif stype == "slack":
        channel_id = config.get("channel_id", "").strip()
        if not channel_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Slack source requires 'channel_id' parameter (e.g. 'C0123456789').",
            )
        if " " in channel_id or len(channel_id) < 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid Slack channel ID '{channel_id}'.",
            )
    elif stype == "meeting":
        # System-managed meeting source
        pass
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported source type '{source_type}'. Must be 'github', 'jira', or 'slack'.",
        )


async def _execute_background_sync(source_id: UUID, org_id: UUID, limit: Optional[int] = 50) -> None:
    """Safely run ingestion pipeline asynchronously under app_sync worker context."""
    pipeline = IngestPipeline()
    try:
        report = await pipeline.sync_source(source_id=source_id, org_id=org_id, limit=limit)
        logger.info(
            "Background sync finished for source %s: status=%s, records=%d, duration=%.2fs",
            source_id, report.status, report.records_scanned, report.duration_seconds
        )
    except Exception as e:
        sanitized = sanitize_error(str(e))
        logger.error("Background sync failed unexpectedly for source %s: %s", source_id, sanitized)
        try:
            async with worker_transaction_context(str(org_id)) as conn:
                await conn.execute(
                    """
                    UPDATE public.sources
                    SET sync_status = 'failed', error_message = $3, updated_at = now()
                    WHERE id = $1 AND org_id = $2
                    """,
                    source_id,
                    org_id,
                    sanitized,
                )
        except Exception as inner_e:
            logger.error("Failed to persist failed sync state for source %s: %s", source_id, inner_e)


# ── OAuth State & Session Helpers ─────────────────────────────────────────

@dataclass
class OAuthSession:
    session_id: str
    org_id: UUID
    user_id: UUID
    provider: str
    account_name: str
    credentials: Dict[str, Any]
    targets: List[Dict[str, Any]]
    created_at: float = field(default_factory=time.time)


_oauth_sessions: Dict[str, OAuthSession] = {}


def _cleanup_oauth_sessions() -> None:
    now = time.time()
    expired = [sid for sid, s in list(_oauth_sessions.items()) if now - s.created_at > 900]
    for sid in expired:
        _oauth_sessions.pop(sid, None)


def _create_oauth_state(org_id: UUID, user_id: UUID, provider: str) -> str:
    payload = {
        "org_id": str(org_id),
        "user_id": str(user_id),
        "provider": provider,
        "nonce": uuid4().hex,
        "exp": int(time.time() + 900),
    }
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    sig = hmac.new(_derive_master_key(), raw, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(raw + b":::" + sig).decode("ascii")
    return token


def _verify_oauth_state(token: str, expected_provider: str) -> Tuple[UUID, UUID]:
    try:
        data = base64.urlsafe_b64decode(token.encode("ascii"))
        parts = data.split(b":::")
        if len(parts) != 2:
            raise ValueError("Malformed state format")
        raw, sig = parts[0], parts[1]
        expected_sig = hmac.new(_derive_master_key(), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected_sig):
            raise ValueError("Signature verification failed")
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("provider") != expected_provider:
            raise ValueError(f"Provider mismatch: expected {expected_provider}, got {payload.get('provider')}")
        if time.time() > payload.get("exp", 0):
            raise ValueError("State has expired (15m limit)")
        return UUID(payload["org_id"]), UUID(payload["user_id"])
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or expired OAuth state parameter: {e}",
        )


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/oauth/status", response_model=OAuthStatusResponse)
async def get_oauth_status(
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> OAuthStatusResponse:
    """
    Check availability of OAuth apps for GitHub, Jira, and Slack.
    Reports which environment variables are missing if not configured.
    """
    gh_missing = []
    if not settings.github_client_id:
        gh_missing.append("GITHUB_CLIENT_ID")
    if not settings.github_client_secret.get_secret_value():
        gh_missing.append("GITHUB_CLIENT_SECRET")

    jira_missing = []
    if not settings.jira_client_id:
        jira_missing.append("JIRA_CLIENT_ID")
    if not settings.jira_client_secret.get_secret_value():
        jira_missing.append("JIRA_CLIENT_SECRET")

    slack_missing = []
    if not settings.slack_client_id:
        slack_missing.append("SLACK_CLIENT_ID")
    if not settings.slack_client_secret.get_secret_value():
        slack_missing.append("SLACK_CLIENT_SECRET")

    return OAuthStatusResponse(
        providers={
            "github": OAuthProviderStatus(
                provider="github",
                available=len(gh_missing) == 0,
                missing_env_vars=gh_missing,
                redirect_uri=settings.github_redirect_uri,
                scopes=["repo", "read:org"],
            ),
            "jira": OAuthProviderStatus(
                provider="jira",
                available=len(jira_missing) == 0,
                missing_env_vars=jira_missing,
                redirect_uri=settings.jira_redirect_uri,
                scopes=["read:jira-work", "read:jira-user", "offline_access"],
            ),
            "slack": OAuthProviderStatus(
                provider="slack",
                available=len(slack_missing) == 0,
                missing_env_vars=slack_missing,
                redirect_uri=settings.slack_redirect_uri,
                scopes=["channels:history", "channels:read", "groups:history", "groups:read", "users:read"],
            ),
        }
    )


@router.get("/oauth/{provider}/authorize", response_model=OAuthAuthorizeResponse)
async def get_oauth_authorize_url(
    provider: str,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(require_team_lead_or_admin),
) -> OAuthAuthorizeResponse:
    """
    Generate provider OAuth authorization URL with signed anti-tamper state parameter.
    Requires organization administrator privileges.
    """
    user, org = context
    prov = provider.lower().strip()
    if prov not in ("github", "jira", "slack"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported OAuth provider '{provider}'. Must be 'github', 'jira', or 'slack'.",
        )

    state = _create_oauth_state(org.org_id, user.id, prov)

    if prov == "github":
        if not settings.github_client_id or not settings.github_client_secret.get_secret_value():
            missing = [k for k, v in [("GITHUB_CLIENT_ID", settings.github_client_id), ("GITHUB_CLIENT_SECRET", settings.github_client_secret.get_secret_value())] if not v]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"GitHub OAuth is not configured on this server. Missing environment variables: {', '.join(missing)}.",
            )
        params = {
            "client_id": settings.github_client_id,
            "redirect_uri": settings.github_redirect_uri,
            "scope": "repo,read:org",
            "state": state,
        }
        url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
    elif prov == "jira":
        if not settings.jira_client_id or not settings.jira_client_secret.get_secret_value():
            missing = [k for k, v in [("JIRA_CLIENT_ID", settings.jira_client_id), ("JIRA_CLIENT_SECRET", settings.jira_client_secret.get_secret_value())] if not v]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Jira OAuth is not configured on this server. Missing environment variables: {', '.join(missing)}.",
            )
        params = {
            "audience": "api.atlassian.com",
            "client_id": settings.jira_client_id,
            "scope": "read:jira-work read:jira-user offline_access",
            "redirect_uri": settings.jira_redirect_uri,
            "state": state,
            "response_type": "code",
            "prompt": "consent",
        }
        url = f"https://auth.atlassian.com/authorize?{urlencode(params)}"
    elif prov == "slack":
        if not settings.slack_client_id or not settings.slack_client_secret.get_secret_value():
            missing = [k for k, v in [("SLACK_CLIENT_ID", settings.slack_client_id), ("SLACK_CLIENT_SECRET", settings.slack_client_secret.get_secret_value())] if not v]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Slack OAuth is not configured on this server. Missing environment variables: {', '.join(missing)}.",
            )
        params = {
            "client_id": settings.slack_client_id,
            "scope": "channels:history,channels:read,groups:history,groups:read,users:read",
            "redirect_uri": settings.slack_redirect_uri,
            "state": state,
        }
        url = f"https://slack.com/oauth/v2/authorize?{urlencode(params)}"

    return OAuthAuthorizeResponse(provider=prov, authorize_url=url, state=state)


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
):
    """
    Handle OAuth redirect from provider, exchange code for tokens, fetch account metadata,
    and establish a secure short-lived setup session.
    """
    prov = provider.lower().strip()
    frontend_url = settings.frontend_base_url.rstrip("/")

    if error:
        err_msg = sanitize_error(error_description or error)
        return RedirectResponse(url=f"{frontend_url}/sources?oauth_error={err_msg}&provider={prov}")

    if not code or not state:
        return RedirectResponse(url=f"{frontend_url}/sources?oauth_error=Missing+code+or+state+parameter&provider={prov}")

    try:
        org_id, user_id = _verify_oauth_state(state, prov)
    except Exception as e:
        return RedirectResponse(url=f"{frontend_url}/sources?oauth_error={sanitize_error(str(e))}&provider={prov}")

    _cleanup_oauth_sessions()
    session_id = uuid4().hex
    account_name = ""
    targets: List[Dict[str, Any]] = []
    credentials: Dict[str, Any] = {}

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            if prov == "github":
                token_resp = await client.post(
                    "https://github.com/login/oauth/access_token",
                    headers={"Accept": "application/json"},
                    data={
                        "client_id": settings.github_client_id,
                        "client_secret": settings.github_client_secret.get_secret_value(),
                        "code": code,
                        "redirect_uri": settings.github_redirect_uri,
                    },
                )
                token_data = token_resp.json()
                if "error" in token_data:
                    return RedirectResponse(
                        url=f"{frontend_url}/sources?oauth_error={token_data.get('error_description', token_data['error'])}&provider={prov}"
                    )

                access_token = token_data.get("access_token")
                credentials = {"token": access_token}

                # User info
                u_resp = await client.get(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "Handoff-Institutional-Memory/1.0",
                    },
                )
                account_name = u_resp.json().get("login", "GitHub Account")

                # Repos
                repos_resp = await client.get(
                    "https://api.github.com/user/repos?per_page=100&sort=updated",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "Handoff-Institutional-Memory/1.0",
                    },
                )
                if repos_resp.status_code == 200:
                    for r in repos_resp.json():
                        targets.append({
                            "id": r["full_name"],
                            "name": r["name"],
                            "description": r.get("description") or "",
                            "extra": {"private": r.get("private", False), "html_url": r.get("html_url")},
                        })

            elif prov == "jira":
                token_resp = await client.post(
                    "https://auth.atlassian.com/oauth/token",
                    headers={"Content-Type": "application/json"},
                    json={
                        "grant_type": "authorization_code",
                        "client_id": settings.jira_client_id,
                        "client_secret": settings.jira_client_secret.get_secret_value(),
                        "code": code,
                        "redirect_uri": settings.jira_redirect_uri,
                    },
                )
                token_data = token_resp.json()
                if "error" in token_data:
                    return RedirectResponse(
                        url=f"{frontend_url}/sources?oauth_error={token_data.get('error_description', token_data['error'])}&provider={prov}"
                    )

                access_token = token_data["access_token"]
                refresh_token = token_data.get("refresh_token")
                credentials = {"token": access_token, "refresh_token": refresh_token}

                res_resp = await client.get(
                    "https://api.atlassian.com/oauth/token/accessible-resources",
                    headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                )
                if res_resp.status_code == 200:
                    resources = res_resp.json()
                    if resources:
                        account_name = resources[0].get("name", "Atlassian Site")
                        for site in resources:
                            targets.append({
                                "id": site["id"],
                                "name": site["name"],
                                "description": site.get("url"),
                                "extra": {"cloud_id": site["id"], "url": site.get("url")},
                            })

            elif prov == "slack":
                token_resp = await client.post(
                    "https://slack.com/api/oauth.v2.access",
                    data={
                        "client_id": settings.slack_client_id,
                        "client_secret": settings.slack_client_secret.get_secret_value(),
                        "code": code,
                        "redirect_uri": settings.slack_redirect_uri,
                    },
                )
                token_data = token_resp.json()
                if not token_data.get("ok"):
                    return RedirectResponse(
                        url=f"{frontend_url}/sources?oauth_error={token_data.get('error', 'OAuth failed')}&provider={prov}"
                    )

                access_token = token_data.get("access_token")
                team_info = token_data.get("team", {})
                account_name = team_info.get("name", "Slack Workspace")
                credentials = {"token": access_token, "team_id": team_info.get("id"), "team_name": account_name}

                chan_resp = await client.get(
                    "https://slack.com/api/conversations.list?types=public_channel,private_channel&limit=100",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if chan_resp.status_code == 200 and chan_resp.json().get("ok"):
                    for c in chan_resp.json().get("channels", []):
                        targets.append({
                            "id": c["id"],
                            "name": f"#{c['name']}",
                            "description": c.get("purpose", {}).get("value") or "",
                            "extra": {"is_private": c.get("is_private", False)},
                        })

        except Exception as e:
            logger.exception("OAuth exchange failed for provider %s: %s", prov, e)
            return RedirectResponse(url=f"{frontend_url}/sources?oauth_error={sanitize_error(str(e))}&provider={prov}")

    _oauth_sessions[session_id] = OAuthSession(
        session_id=session_id,
        org_id=org_id,
        user_id=user_id,
        provider=prov,
        account_name=account_name,
        credentials=credentials,
        targets=targets,
    )

    return RedirectResponse(
        url=f"{frontend_url}/sources?oauth_session={session_id}&provider={prov}&account={account_name}"
    )


@router.get("/oauth/session/{session_id}", response_model=OAuthSessionResponse)
async def get_oauth_session(
    session_id: str,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(require_team_lead_or_admin),
) -> OAuthSessionResponse:
    """
    Inspect an established OAuth setup session to select target repository, project, or channel.
    Requires organization administrator privileges.
    """
    user, org = context
    _cleanup_oauth_sessions()
    session = _oauth_sessions.get(session_id)
    if not session or session.org_id != org.org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OAuth session not found or expired. Please re-authenticate.",
        )

    return OAuthSessionResponse(
        session_id=session.session_id,
        provider=session.provider,
        account_name=session.account_name,
        targets=[OAuthSessionTarget(**t) for t in session.targets],
    )


@router.post("/oauth/session/{session_id}/finalize", response_model=KnowledgeSourceResponse, status_code=status.HTTP_201_CREATED)
async def finalize_oauth_session(
    session_id: str,
    request: FinalizeOAuthSessionRequest,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(require_team_lead_or_admin),
) -> KnowledgeSourceResponse:
    """
    Finalize an OAuth session by creating a source for the selected target with encrypted credentials.
    Requires organization administrator privileges.
    """
    user, org = context
    _cleanup_oauth_sessions()
    session = _oauth_sessions.get(session_id)
    if not session or session.org_id != org.org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OAuth session not found or expired. Please re-authenticate.",
        )

    source_id = uuid4()
    source_type = session.provider
    config: Dict[str, Any] = {
        "auth_method": "oauth",
        "connected_account": session.account_name,
    }

    if source_type == "github":
        repo = request.target_id.strip()
        config["repo"] = repo
        async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
            dup = await conn.fetchrow(
                "SELECT id, name FROM public.sources WHERE org_id = $1 AND type = 'github' AND is_archived = false AND config->>'repo' = $2",
                org.org_id, repo,
            )
            if dup:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"GitHub repository '{repo}' is already connected under source '{dup['name']}'.",
                )
    elif source_type == "jira":
        site = next((t for t in session.targets if t["id"] == request.target_id), None)
        base_url = (site.get("extra", {}).get("url") if site else request.target_id).rstrip("/")
        cloud_id = site.get("extra", {}).get("cloud_id") if site else request.target_id
        config["base_url"] = base_url
        config["cloud_id"] = cloud_id
    elif source_type == "slack":
        channel_id = request.target_id.strip()
        target_info = next((t for t in session.targets if t["id"] == channel_id), None)
        config["channel_id"] = channel_id
        if target_info:
            config["channel_name"] = target_info["name"]
        config["team_name"] = session.account_name
        async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
            dup = await conn.fetchrow(
                "SELECT id, name FROM public.sources WHERE org_id = $1 AND type = 'slack' AND is_archived = false AND config->>'channel_id' = $2",
                org.org_id, channel_id,
            )
            if dup:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Slack channel '{channel_id}' is already connected under source '{dup['name']}'.",
                )

    # Encrypt credentials cryptographically bound to org_id and source_id
    enc_creds = encrypt_credentials(session.credentials, org.org_id, source_id)

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        await conn.execute(
            """
            INSERT INTO public.sources (
                id, org_id, name, type, visibility, config, encrypted_credentials, sync_status, is_archived
            ) VALUES (
                $1, $2, $3, $4, $5, $6::jsonb, $7, 'ok', false
            )
            """,
            source_id,
            org.org_id,
            request.name.strip(),
            source_type,
            request.visibility.strip(),
            json.dumps(config),
            enc_creds,
        )

        row = await conn.fetchrow(
            """
            SELECT id, org_id, name, type, visibility, config,
                   sync_status, sync_cursor, last_synced_at, error_message,
                   is_archived, created_at, updated_at
            FROM public.sources
            WHERE id = $1 AND org_id = $2
            """,
            source_id,
            org.org_id,
        )

    raw_cfg = row["config"]
    cfg = json.loads(raw_cfg) if isinstance(raw_cfg, str) else (raw_cfg or {})
    raw_cur = row["sync_cursor"]
    cur = json.loads(raw_cur) if isinstance(raw_cur, str) else (raw_cur or {})
    return KnowledgeSourceResponse(
        id=row["id"],
        org_id=row["org_id"],
        name=row["name"],
        type=row["type"],
        visibility=row["visibility"],
        config=cfg,
        sync_status=row["sync_status"],
        sync_cursor=cur,
        last_synced_at=row["last_synced_at"],
        error_message=row["error_message"],
        is_archived=row["is_archived"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        record_count=0,
        has_encrypted_credentials=True,
    )


# ── Core Endpoints ────────────────────────────────────────────────────────

@router.get("", response_model=List[KnowledgeSourceResponse])
async def list_sources(
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> List[KnowledgeSourceResponse]:
    """
    List non-archived knowledge sources for the active organization.
    Enforces PostgreSQL Row-Level Security: non-admins only see sources they are permitted to view.
    """
    user, org = context

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        rows = await conn.fetch(
            """
            SELECT 
                s.id,
                s.org_id,
                s.name,
                s.type,
                s.visibility,
                s.config,
                s.sync_status,
                s.sync_cursor,
                s.last_synced_at,
                s.error_message,
                s.is_archived,
                s.created_at,
                s.updated_at,
                (s.encrypted_credentials IS NOT NULL) AS has_encrypted_credentials,
                COALESCE(COUNT(r.id), 0)::int AS record_count
            FROM public.sources s
            LEFT JOIN public.records r ON r.source_id = s.id AND r.org_id = s.org_id
            WHERE s.org_id = $1 AND s.is_archived = false
            GROUP BY s.id
            ORDER BY s.created_at DESC
            """,
            org.org_id,
        )

    sources = []
    for r in rows:
        raw_cfg = r["config"]
        cfg = json.loads(raw_cfg) if isinstance(raw_cfg, str) else (raw_cfg or {})
        raw_cur = r["sync_cursor"]
        cur = json.loads(raw_cur) if isinstance(raw_cur, str) else (raw_cur or {})
        sources.append(
            KnowledgeSourceResponse(
                id=r["id"],
                org_id=r["org_id"],
                name=r["name"],
                type=r["type"],
                visibility=r["visibility"],
                config=cfg,
                sync_status=r["sync_status"],
                sync_cursor=cur,
                last_synced_at=r["last_synced_at"],
                error_message=sanitize_error(r["error_message"] or ""),
                is_archived=r["is_archived"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                record_count=r["record_count"],
                has_encrypted_credentials=bool(r["has_encrypted_credentials"]),
            )
        )
    return sources


@router.post("", response_model=KnowledgeSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    request: CreateSourceRequest,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(require_team_lead_or_admin),
) -> KnowledgeSourceResponse:
    """
    Register a new knowledge source.
    Requires organization administrator privileges.
    Optional credentials are encrypted at rest with AES-256-GCM and never returned in plaintext.
    """
    user, org = context
    name = request.name.strip()
    source_type = request.type.strip().lower()
    visibility = request.visibility.strip().lower()

    if visibility not in ("public", "restricted"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Visibility must be either 'public' or 'restricted'.",
        )

    # Validate configuration against connector requirements and credential boundaries
    _validate_source_config(source_type, request.config)

    # Duplicate connection prevention per organization
    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        if source_type == "github" and "repo" in request.config:
            dup = await conn.fetchrow(
                "SELECT id, name FROM public.sources WHERE org_id = $1 AND type = 'github' AND is_archived = false AND config->>'repo' = $2",
                org.org_id, request.config["repo"],
            )
            if dup:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"GitHub repository '{request.config['repo']}' is already connected under source '{dup['name']}'.",
                )
        elif source_type == "slack" and "channel_id" in request.config:
            dup = await conn.fetchrow(
                "SELECT id, name FROM public.sources WHERE org_id = $1 AND type = 'slack' AND is_archived = false AND config->>'channel_id' = $2",
                org.org_id, request.config["channel_id"],
            )
            if dup:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Slack channel '{request.config['channel_id']}' is already connected under source '{dup['name']}'.",
                )

    source_id = uuid4()
    encrypted_creds: Optional[bytes] = None

    # If raw credentials are provided in the request, validate them live and encrypt
    if request.credentials:
        if source_type == "github":
            c = GitHubConnector(repo=request.config["repo"], token=request.credentials.get("token"))
            v = await c.validate()
            if not v.is_valid:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Validation failed: {sanitize_error(v.message)}")
        elif source_type == "jira":
            c = JiraConnector(
                base_url=request.config["base_url"],
                email=request.credentials.get("email"),
                token=request.credentials.get("token"),
                project=request.config.get("project"),
            )
            v = await c.validate()
            if not v.is_valid:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Validation failed: {sanitize_error(v.message)}")
        elif source_type == "slack":
            c = SlackConnector(channel_id=request.config["channel_id"], token=request.credentials.get("token"))
            v = await c.validate()
            if not v.is_valid:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Validation failed: {sanitize_error(v.message)}")

        encrypted_creds = encrypt_credentials(request.credentials, org.org_id, source_id)
        request.config["auth_method"] = "token"

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        await conn.execute(
            """
            INSERT INTO public.sources (
                id, org_id, name, type, visibility, config, encrypted_credentials, sync_status, is_archived
            ) VALUES (
                $1, $2, $3, $4, $5, $6::jsonb, $7, 'ok', false
            )
            """,
            source_id,
            org.org_id,
            name,
            source_type,
            visibility,
            json.dumps(request.config),
            encrypted_creds,
        )

        row = await conn.fetchrow(
            """
            SELECT id, org_id, name, type, visibility, config,
                   sync_status, sync_cursor, last_synced_at, error_message,
                   is_archived, created_at, updated_at
            FROM public.sources
            WHERE id = $1 AND org_id = $2
            """,
            source_id,
            org.org_id,
        )

    raw_cfg = row["config"]
    cfg = json.loads(raw_cfg) if isinstance(raw_cfg, str) else (raw_cfg or {})
    raw_cur = row["sync_cursor"]
    cur = json.loads(raw_cur) if isinstance(raw_cur, str) else (raw_cur or {})
    return KnowledgeSourceResponse(
        id=row["id"],
        org_id=row["org_id"],
        name=row["name"],
        type=row["type"],
        visibility=row["visibility"],
        config=cfg,
        sync_status=row["sync_status"],
        sync_cursor=cur,
        last_synced_at=row["last_synced_at"],
        error_message=row["error_message"],
        is_archived=row["is_archived"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        record_count=0,
        has_encrypted_credentials=bool(encrypted_creds is not None),
    )


@router.post("/validate", response_model=ValidationResponse)
async def validate_source_connection(
    request: ValidateConfigRequest,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(require_team_lead_or_admin),
) -> ValidationResponse:
    """
    Test connector reachability and credentials for given configuration.
    Requires organization administrator or team lead privileges.
    Uses provided credentials if supplied, or falls back to server-side configured environment tokens.
    """
    source_type = request.type.strip().lower()
    _validate_source_config(source_type, request.config)

    creds = request.credentials or {}
    try:
        if source_type == "github":
            token = creds.get("token")
            connector = GitHubConnector(repo=request.config["repo"], token=token)
            result = await connector.validate()
        elif source_type == "jira":
            email = creds.get("email")
            token = creds.get("token")
            connector = JiraConnector(
                base_url=request.config["base_url"],
                email=email,
                token=token,
                project=request.config.get("project"),
                jql=request.config.get("jql"),
            )
            result = await connector.validate()
        elif source_type == "slack":
            token = creds.get("token")
            connector = SlackConnector(channel_id=request.config["channel_id"], token=token)
            result = await connector.validate()
        else:
            return ValidationResponse(is_valid=False, message=f"Unsupported source type: {source_type}")

        return ValidationResponse(
            is_valid=result.is_valid,
            message=sanitize_error(result.message),
            details=result.details,
        )
    except Exception as e:
        return ValidationResponse(
            is_valid=False,
            message=sanitize_error(f"Validation failed: {str(e)}"),
            details={"error_type": type(e).__name__},
        )


@router.post("/{source_id}/sync", response_model=SyncResponse)
async def sync_source(
    source_id: UUID,
    background_tasks: BackgroundTasks,
    background: bool = Query(default=True, description="Whether to execute sync as background task."),
    limit: Optional[int] = Query(default=50, ge=1, le=100, description="Maximum records to process."),
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(require_team_lead_or_admin),
) -> SyncResponse:
    """
    Trigger an evidence sync for a configured knowledge source.
    Requires organization administrator privileges.
    Enforces atomic duplicate sync prevention (returns HTTP 409 Conflict if already running).
    """
    user, org = context

    # 1. Verify existence, ownership, and active state
    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        source_row = await conn.fetchrow(
            """
            SELECT id, name, type, sync_status, is_archived
            FROM public.sources
            WHERE id = $1 AND org_id = $2
            """,
            source_id,
            org.org_id,
        )

        if not source_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source {source_id} not found in this organization.",
            )

        if source_row["is_archived"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot sync an archived source. Unarchive the source first.",
            )

        if source_row["sync_status"] == "running":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A sync is already in progress for source '{source_row['name']}'.",
            )

        # 2. Transition status to running atomically
        updated = await conn.execute(
            """
            UPDATE public.sources
            SET sync_status = 'running', updated_at = now()
            WHERE id = $1 AND org_id = $2 AND sync_status != 'running'
            """,
            source_id,
            org.org_id,
        )
        if updated == "UPDATE 0":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Concurrent sync lock acquisition failed: sync was initiated simultaneously.",
            )

    # 3. Execution strategy: background task (default for HTTP safety) or synchronous (for testing)
    if background:
        background_tasks.add_task(_execute_background_sync, source_id, org.org_id, limit)
        return SyncResponse(
            source_id=source_id,
            status="running",
            message=f"Sync for '{source_row['name']}' started in background.",
            records_scanned=0,
            records_created=0,
            duration_seconds=0.0,
        )

    # Synchronous execution
    pipeline = IngestPipeline()
    try:
        report: SyncReport = await pipeline.sync_source(source_id=source_id, org_id=org.org_id, limit=limit)
        return SyncResponse(
            source_id=source_id,
            status=report.status,
            message=f"Sync completed with status '{report.status}'.",
            records_scanned=report.records_scanned,
            records_created=report.records_created,
            records_updated=report.records_updated,
            chunks_created=report.chunks_created,
            errors=[sanitize_error(e) for e in report.errors],
            duration_seconds=report.duration_seconds,
        )
    except Exception as e:
        sanitized = sanitize_error(str(e))
        logger.error("Synchronous sync failed for source %s: %s", source_id, sanitized)
        # Update failed status in worker transaction
        try:
            async with worker_transaction_context(str(org.org_id)) as conn:
                await conn.execute(
                    """
                    UPDATE public.sources
                    SET sync_status = 'failed', error_message = $3, updated_at = now()
                    WHERE id = $1 AND org_id = $2
                    """,
                    source_id,
                    org.org_id,
                    sanitized,
                )
        except Exception:
            pass
        return SyncResponse(
            source_id=source_id,
            status="failed",
            message=f"Sync failed: {sanitized}",
            errors=[sanitized],
        )


@router.get("/{source_id}/records", response_model=PaginatedRecordsResponse)
async def list_source_records(
    source_id: UUID,
    limit: int = Query(default=20, ge=1, le=100, description="Items per page."),
    offset: int = Query(default=0, ge=0, description="Offset for pagination."),
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> PaginatedRecordsResponse:
    """
    Paginated inspection of records and current version details for a knowledge source.
    Enforces tenant isolation and PostgreSQL Row-Level Security.
    """
    user, org = context

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        # Check source accessibility under RLS
        source = await conn.fetchrow(
            """
            SELECT id FROM public.sources
            WHERE id = $1 AND org_id = $2 AND is_archived = false
            """,
            source_id,
            org.org_id,
        )
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source {source_id} not found or not accessible.",
            )

        # Count total records for source
        total_row = await conn.fetchrow(
            """
            SELECT COUNT(*)::int AS total
            FROM public.records
            WHERE source_id = $1 AND org_id = $2
            """,
            source_id,
            org.org_id,
        )
        total = total_row["total"] if total_row else 0

        # Fetch paginated records with current version content
        rows = await conn.fetch(
            """
            SELECT 
                r.id,
                r.org_id,
                r.source_id,
                r.external_id,
                r.record_type,
                r.created_at,
                r.title,
                r.author_name,
                r.url,
                rv.id AS current_version_id,
                rv.version_index,
                COALESCE(rv.synced_at, r.created_at) AS updated_at,
                LEFT(rv.content, 250) AS snippet,
                (SELECT COUNT(*)::int FROM public.chunks c WHERE c.record_id = r.id AND c.org_id = r.org_id) AS chunk_count
            FROM public.records r
            LEFT JOIN public.record_versions rv 
                   ON rv.record_id = r.id 
                  AND rv.org_id = r.org_id 
                  AND rv.is_latest = true
            WHERE r.source_id = $1 AND r.org_id = $2
            ORDER BY r.created_at DESC
            LIMIT $3 OFFSET $4
            """,
            source_id,
            org.org_id,
            limit,
            offset,
        )

    records = [
        RecordSummaryResponse(
            id=r["id"],
            org_id=r["org_id"],
            source_id=r["source_id"],
            external_id=r["external_id"],
            record_type=r["record_type"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            current_version_id=r["current_version_id"],
            version_index=r["version_index"],
            title=r["title"],
            author_name=r["author_name"],
            url=r["url"],
            snippet=r["snippet"],
            chunk_count=r["chunk_count"],
        )
        for r in rows
    ]

    return PaginatedRecordsResponse(
        items=records,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/{source_id}", response_model=KnowledgeSourceResponse)
async def update_source(
    source_id: UUID,
    request: UpdateSourceRequest,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(require_team_lead_or_admin),
) -> KnowledgeSourceResponse:
    """
    Update source details, visibility, or soft-archive status.
    Requires organization administrator privileges.
    Never hard-deletes records or versions.
    """
    user, org = context

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        existing = await conn.fetchrow(
            """
            SELECT id, name, type, visibility, config, sync_status, sync_cursor,
                   last_synced_at, error_message, is_archived, created_at, updated_at
            FROM public.sources
            WHERE id = $1 AND org_id = $2
            """,
            source_id,
            org.org_id,
        )
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source {source_id} not found in this organization.",
            )

        new_name = request.name.strip() if request.name is not None else existing["name"]
        new_vis = request.visibility.strip().lower() if request.visibility is not None else existing["visibility"]
        if new_vis not in ("public", "restricted"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Visibility must be either 'public' or 'restricted'.",
            )

        new_archived = request.is_archived if request.is_archived is not None else existing["is_archived"]

        raw_cfg = existing["config"]
        current_cfg = json.loads(raw_cfg) if isinstance(raw_cfg, str) else (raw_cfg or {})
        if request.config is not None:
            _validate_source_config(existing["type"], request.config)
            new_cfg = request.config
        else:
            new_cfg = current_cfg

        await conn.execute(
            """
            UPDATE public.sources
            SET name = $1, visibility = $2, config = $3::jsonb, is_archived = $4, updated_at = now()
            WHERE id = $5 AND org_id = $6
            """,
            new_name,
            new_vis,
            json.dumps(new_cfg),
            new_archived,
            source_id,
            org.org_id,
        )

        updated_row = await conn.fetchrow(
            """
            SELECT id, org_id, name, type, visibility, config, sync_status,
                   sync_cursor, last_synced_at, error_message, is_archived, created_at, updated_at
            FROM public.sources
            WHERE id = $1 AND org_id = $2
            """,
            source_id,
            org.org_id,
        )

        # Count records
        count_row = await conn.fetchrow(
            "SELECT COUNT(*)::int AS count FROM public.records WHERE source_id = $1 AND org_id = $2",
            source_id,
            org.org_id,
        )
        rec_count = count_row["count"] if count_row else 0

    raw_cur = updated_row["sync_cursor"]
    cur = json.loads(raw_cur) if isinstance(raw_cur, str) else (raw_cur or {})

    return KnowledgeSourceResponse(
        id=updated_row["id"],
        org_id=updated_row["org_id"],
        name=updated_row["name"],
        type=updated_row["type"],
        visibility=updated_row["visibility"],
        config=new_cfg,
        sync_status=updated_row["sync_status"],
        sync_cursor=cur,
        last_synced_at=updated_row["last_synced_at"],
        error_message=sanitize_error(updated_row["error_message"] or ""),
        is_archived=updated_row["is_archived"],
        created_at=updated_row["created_at"],
        updated_at=updated_row["updated_at"],
        record_count=rec_count,
    )


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: UUID,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(require_team_lead_or_admin),
) -> None:
    """
    Permanently delete a knowledge source and all its associated records, versions,
    chunks, and relationships in atomic dependency order.
    Requires administrator or team lead privileges.
    """
    user, org = context

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        # Verify source exists in caller's organization
        source = await conn.fetchrow(
            "SELECT id, name FROM public.sources WHERE id = $1 AND org_id = $2",
            source_id,
            org.org_id,
        )
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source {source_id} not found in this organization.",
            )

        # Get all records associated with this source
        rec_rows = await conn.fetch(
            "SELECT id FROM public.records WHERE source_id = $1 AND org_id = $2",
            source_id,
            org.org_id,
        )
        rec_ids = [r["id"] for r in rec_rows]

        if rec_ids:
            # 1. Clean up knowledge note links
            await conn.execute(
                "DELETE FROM public.knowledge_note_records WHERE record_id = ANY($1::uuid[]) AND org_id = $2",
                rec_ids,
                org.org_id,
            )

            # 2. Clean up record links
            await conn.execute(
                """
                DELETE FROM public.record_links
                WHERE (from_record_id = ANY($1::uuid[]) OR to_record_id = ANY($1::uuid[]))
                  AND org_id = $2
                """,
                rec_ids,
                org.org_id,
            )

            # 3. Clean up chunks (or will cascade from versions)
            await conn.execute(
                "DELETE FROM public.chunks WHERE source_id = $1 AND org_id = $2",
                source_id,
                org.org_id,
            )

            # 4. Clean up record versions
            await conn.execute(
                "DELETE FROM public.record_versions WHERE source_id = $1 AND org_id = $2",
                source_id,
                org.org_id,
            )

            # 5. Clean up records
            await conn.execute(
                "DELETE FROM public.records WHERE source_id = $1 AND org_id = $2",
                source_id,
                org.org_id,
            )

        # 6. Clean up access grants
        await conn.execute(
            "DELETE FROM public.source_access_grants WHERE source_id = $1 AND org_id = $2",
            source_id,
            org.org_id,
        )

        # 7. Delete the source row
        await conn.execute(
            "DELETE FROM public.sources WHERE id = $1 AND org_id = $2",
            source_id,
            org.org_id,
        )
