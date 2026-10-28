"""
API router for grounded question answering and verification.
Provides POST /api/ask endpoint protected by Supabase Auth and tenant isolation.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from apps.api.agent.agent import AgentResponse, InstitutionalMemoryAgent
from apps.api.auth.dependencies import (
    ActiveOrganization,
    AuthenticatedUser,
    get_organization_context,
)
from apps.api.db.pool import transaction_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["agent"])


class AskRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="Engineering question about decisions or systems.",
        examples=["Why did we migrate from REST to gRPC for the payments service?"],
    )
    persist: bool = Field(
        default=True,
        description="Whether to persist answer and claims to database.",
    )


class VerifiedClaimResponse(BaseModel):
    claim_text: str
    record_id: str
    record_version_id: str
    chunk_id: str
    exact_quote: str
    quote_offset: Optional[int] = None
    verification_status: str
    evidence_type: str
    record_title: str
    record_url: Optional[str] = None
    record_type: Optional[str] = None


class AskResponse(BaseModel):
    answer_id: Optional[str] = None
    question: str
    answer: str
    evidence_level: str
    evidence_reason: str
    is_abstention: bool
    staleness_warning: Optional[str] = None
    claims: List[VerifiedClaimResponse] = Field(default_factory=list)
    investigation_trace: List[Dict[str, Any]] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)


@router.post("/ask", response_model=AskResponse)
async def ask_question(
    request: AskRequest,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> AskResponse:
    """
    Submit an engineering question to the Institutional Memory Agent.
    Executes bounded retrieval, grounded DSPy reasoning, deterministic citation verification,
    and safe PostgreSQL persistence under the caller's verified organization context.
    """
    user, org = context
    agent = InstitutionalMemoryAgent()

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        try:
            response: AgentResponse = await agent.answer(
                user_id=user.id,
                org_id=org.org_id,
                question=request.question,
                connection=conn,
            )
        except RuntimeError as e:
            if "GROQ_API_KEY" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=str(e),
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Agent error: {e}",
            )
        except Exception as e:
            logger.error("Unhandled error in ask_question: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Agent investigation failed: {e}",
            )

        if request.persist and not response.is_abstention and response.claims:
            try:
                await agent.persist(
                    response=response,
                    user_id=user.id,
                    org_id=org.org_id,
                    connection=conn,
                )
            except Exception as e:
                logger.warning("Could not persist answer to database: %s", e)
        elif request.persist and response.is_abstention:
            # Also persist abstentions so queries without answers are audited
            try:
                await agent.persist(
                    response=response,
                    user_id=user.id,
                    org_id=org.org_id,
                    connection=conn,
                )
            except Exception as e:
                logger.warning("Could not persist abstention to database: %s", e)

        return AskResponse(
            answer_id=response.answer_id,
            question=response.question,
            answer=response.answer,
            evidence_level=response.evidence_level,
            evidence_reason=response.evidence_reason,
            is_abstention=response.is_abstention,
            staleness_warning=response.staleness_warning,
            claims=[
                VerifiedClaimResponse(
                    claim_text=c.claim_text,
                    record_id=c.record_id,
                    record_version_id=c.record_version_id,
                    chunk_id=c.chunk_id,
                    exact_quote=c.exact_quote,
                    quote_offset=c.quote_offset,
                    verification_status=c.verification_status,
                    evidence_type=c.evidence_type,
                    record_title=c.record_title,
                    record_url=c.record_url,
                    record_type=c.record_type,
                )
                for c in response.claims
            ],
            investigation_trace=response.investigation_trace,
            metrics=response.metrics,
        )

