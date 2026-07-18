from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_db_session
from app.feedback.repository import FeedbackRepository
from app.feedback.service import FeedbackService


def get_feedback_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FeedbackRepository:
    return FeedbackRepository(session)


def get_feedback_service(
    repository: Annotated[FeedbackRepository, Depends(get_feedback_repository)],
) -> FeedbackService:
    return FeedbackService(repository)
