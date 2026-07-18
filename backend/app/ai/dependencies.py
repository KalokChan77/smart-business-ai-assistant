from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.factory import ProviderFactory
from app.ai.repository import AIRunsRepository
from app.ai.service import AIChatService
from app.conversations.dependencies import get_conversation_service
from app.conversations.service import ConversationService
from app.db.dependencies import get_db_session


def get_ai_runs_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AIRunsRepository:
    return AIRunsRepository(session)


def get_provider_factory(request: Request) -> ProviderFactory:
    return ProviderFactory(request.app.state.settings)


def get_ai_chat_service(
    request: Request,
    runs: Annotated[AIRunsRepository, Depends(get_ai_runs_repository)],
    conversations: Annotated[ConversationService, Depends(get_conversation_service)],
    providers: Annotated[ProviderFactory, Depends(get_provider_factory)],
) -> AIChatService:
    return AIChatService(
        runs=runs,
        conversations=conversations,
        providers=providers,
        history_limit=request.app.state.settings.ai_history_message_limit,
    )
