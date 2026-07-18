from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversations.repository import ConversationsRepository
from app.conversations.service import ConversationService
from app.db.dependencies import get_db_session


def get_conversation_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConversationsRepository:
    return ConversationsRepository(session)


def get_conversation_service(
    repository: Annotated[
        ConversationsRepository,
        Depends(get_conversation_repository),
    ],
) -> ConversationService:
    return ConversationService(repository)
