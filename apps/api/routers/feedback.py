"""
API router for submitting user feedback on investigation answers.
Enforces author ownership and strictly isolates mutations to feedback fields.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from apps.api.auth.dependencies import (
    ActiveOrganization,
    AuthenticatedUser,
    get_organization_context,
)
from apps.api.db.pool import transaction_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/answers", tags=["feedback"])


class AnswerFeedbackRequest(BaseModel):
    rating: int = Field(..., description="+1 for helpful/accurate, -1 for unhelpful/inaccurate.")
    notes: Optional[str] = Field(default=None, max_length=2000, description="Optional explanation or correction notes.")


class AnswerFeedbackResponse(BaseModel):
    answer_id: UUID
    feedback_rating: int
    feedback_notes: Optional[str] = None
    updated_at: datetime


@router.post("/{answer_id}/feedback", response_model=AnswerFeedbackResponse)
async def submit_answer_feedback(
    answer_id: UUID,
    request: AnswerFeedbackRequest,
    context: tuple[AuthenticatedUser, ActiveOrganization] = Depends(get_organization_context),
) -> AnswerFeedbackResponse:
    """
    Submit user feedback (+1 / -1 and optional notes) for an investigation answer.
    Enforces that only the user who asked/created the question-answer can provide feedback.
    Strictly updates feedback_rating and feedback_notes without mutating core claims or trace data.
    """
    user, org = context

    if request.rating not in (1, -1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Feedback rating must be either 1 or -1.",
        )

    async with transaction_context(user_id=user.id, org_id=org.org_id) as conn:
        answer = await conn.fetchrow(
            """
            SELECT id, created_by_user_id
            FROM public.answers
            WHERE id = $1 AND org_id = $2;
            """,
            answer_id,
            org.org_id,
        )

        if not answer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Answer not found in the current organization.",
            )

        # Enforce that only the creator can rate their answer
        if answer["created_by_user_id"] != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: you can only submit feedback for answers you generated.",
            )

        updated_row = await conn.fetchrow(
            """
            UPDATE public.answers
            SET feedback_rating = $1,
                feedback_notes = $2
            WHERE id = $3 AND org_id = $4 AND created_by_user_id = $5
            RETURNING id, feedback_rating, feedback_notes, created_at;
            """,
            request.rating,
            request.notes.strip() if request.notes else None,
            answer_id,
            org.org_id,
            user.id,
        )

        if not updated_row:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not update feedback for this answer.",
            )

        return AnswerFeedbackResponse(
            answer_id=updated_row["id"],
            feedback_rating=updated_row["feedback_rating"],
            feedback_notes=updated_row["feedback_notes"],
            updated_at=datetime.now(timezone.utc),
        )
