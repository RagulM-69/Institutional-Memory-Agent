"""
FastAPI application entry point.

This module creates the FastAPI app, configures CORS for local development,
and mounts the /health route. No routers, auth, or database logic are
included here — those are added in later phases.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Institutional Memory Agent API",
    description="Backend for the Institutional Memory Agent.",
    version="0.1.0",
)

# CORS: allow the Next.js dev server in local development.
# This will be tightened to the production URL when deployed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness check. Returns ok when the process is running."""
    return {"status": "ok"}

