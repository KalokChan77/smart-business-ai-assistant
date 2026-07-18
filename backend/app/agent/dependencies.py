from typing import Annotated

from fastapi import Depends, Request

from app.agent.graph import AgentGraphFactory
from app.agent.model_factory import AgentModelFactory
from app.agent.service import AgentService
from app.agent.tools import registered_tools
from app.ai.dependencies import get_ai_runs_repository
from app.ai.repository import AIRunsRepository
from app.conversations.dependencies import get_conversation_service
from app.conversations.service import ConversationService


def get_agent_model_factory(request: Request) -> AgentModelFactory:
    return AgentModelFactory(request.app.state.settings)


def get_agent_graph_factory() -> AgentGraphFactory:
    return AgentGraphFactory(registered_tools())


def get_agent_service(
    request: Request,
    runs: Annotated[AIRunsRepository, Depends(get_ai_runs_repository)],
    conversations: Annotated[ConversationService, Depends(get_conversation_service)],
    models: Annotated[AgentModelFactory, Depends(get_agent_model_factory)],
    graphs: Annotated[AgentGraphFactory, Depends(get_agent_graph_factory)],
) -> AgentService:
    settings = request.app.state.settings
    return AgentService(
        runs=runs,
        conversations=conversations,
        models=models,
        graphs=graphs,
        history_limit=settings.agent_history_message_limit,
        recursion_limit=settings.agent_recursion_limit,
    )
