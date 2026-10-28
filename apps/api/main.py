"""
FastAPI application entry point.

Configures CORS, lifespan database pool management, public /health route,
and authenticated identity & organization endpoints.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.auth.dependencies import (
    ActiveOrganization,
    AuthenticatedUser,
    get_current_user,
    get_organization_context,
)
from apps.api.config import settings
from apps.api.db.pool import close_pool, init_pool
from apps.api.routers.ask import router as ask_router
from apps.api.routers.feedback import router as feedback_router
from apps.api.routers.handoffs import router as handoffs_router
from apps.api.routers.invitations import router as invitations_router
from apps.api.routers.knowledge import router as knowledge_router
from apps.api.routers.meetings import router as meetings_router
from apps.api.routers.organizations import router as organizations_router
from apps.api.routers.sources import router as sources_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application resources: initialize DB pool on startup, close on shutdown."""
    if settings.database_url.get_secret_value():
        try:
            await init_pool()
            logger.info("Database pool initialized successfully")
        except Exception as e:
            logger.warning("Could not pre-initialize database pool at startup: %s", e)
    yield
    await close_pool()


app = FastAPI(
    title="Institutional Memory Agent API",
    description="Backend for the Institutional Memory Agent.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: allow local Next.js dev server, Vercel deployments, and custom frontends.
cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
if settings.frontend_base_url and settings.frontend_base_url not in cors_origins:
    cors_origins.append(settings.frontend_base_url.rstrip("/"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"^https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness check. Returns ok when the process is running. Publicly accessible."""
    return {"status": "ok"}


@app.get("/api/me", tags=["auth"])
async def get_me(user: AuthenticatedUser = Depends(get_current_user)) -> dict[str, str | None]:
    """Returns the cryptographically verified user identity."""
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
    }


@app.get("/api/organization/current", tags=["auth"])
async def get_current_org(
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> dict[str, str]:
    """Returns the verified active organization and user membership role."""
    user, org = context
    return {
        "user_id": str(user.id),
        "org_id": str(org.org_id),
        "name": org.name,
        "slug": org.slug,
        "role": org.role,
    }


# Agent & Investigation Routes
app.include_router(ask_router)
app.include_router(knowledge_router)
app.include_router(meetings_router)
app.include_router(handoffs_router)
app.include_router(feedback_router)
app.include_router(sources_router)
app.include_router(organizations_router)
app.include_router(invitations_router)

